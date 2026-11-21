from collections import Counter
from datetime import datetime, UTC, timedelta
from datetime import date

from app.accounts import preferences, set_preferences
from app.briefing import service
from app.briefing.contracts import BriefingRequest
from app.briefing.daily import daily_key, ensure_daily
from app.briefing.duration import speaking_rate
from app.briefing.models import Briefing, BriefingSegment, GeneratedAudio
from test_listener_workflow import session, listener


def test_rate_adapts_to_recent_distinct_recordings_instead_of_old_pacing(session):
    user = listener(session, "recent-rate", "en", [])
    for index, words in enumerate([100] * 8 + [160, 180, 170]):
        audio = GeneratedAudio(
            cache_key="recent-" + str(index),
            object_key=str(index),
            duration_seconds=60,
            boundaries=[],
            provider="elevenlabs",
        )
        session.add(audio)
        session.flush()
        item = Briefing(
            user_id=user.id,
            title="Rate",
            status="completed",
            language="en",
            voice_profile_id="energetic",
            request={},
            duration_seconds=60,
            audio_id=audio.id,
            created_at=datetime.now(UTC) + timedelta(seconds=index),
        )
        session.add(item)
        session.flush()
        session.add(
            BriefingSegment(
                briefing_id=item.id,
                position=0,
                text="word " * words,
                language="en",
                claim_ids=[],
                source_article_ids=[],
                citations=[],
                verification_status="editorial",
            )
        )
    session.flush()
    assert speaking_rate(session, "en", "energetic") == 170


def test_voice_copy_adds_verified_detail_when_a_faster_voice_would_be_too_short(
    session, monkeypatch
):
    from app.briefing import duration

    user = listener(session, "fast-copy", "en", ["technology"])
    set_preferences(session, user.id, {"duration_minutes": 1})
    source = ensure_daily(session, user.id)
    service.generate_script(session, source.id)
    original = service.segments_for(session, source.id)
    original_words = sum(len(s.text.split()) for s in original)
    from app.news.models import Article, Fact, ClaimEvidence

    line = next(row for row in original if row.claim_ids)
    article = session.get(Article, line.source_article_ids[0])
    for index in range(6):
        text = f"Aurora reported project {index} opened a new regional research facility with additional engineering equipment and twenty permanent staff positions."
        start = len(article.content) + 1
        article.content += " " + text
        fact = Fact(
            story_id=line.story_id, text=text, language="en", status="supported"
        )
        session.add(fact)
        session.flush()
        session.add(
            ClaimEvidence(
                fact_id=fact.id,
                article_id=article.id,
                excerpt=text,
                start=start,
                end=start + len(text),
            )
        )
    session.commit()
    set_preferences(session, user.id, {"voice_profile_id": "jarvis"})
    monkeypatch.setattr(duration, "speaking_rate", lambda *args: 210)
    monkeypatch.setattr(service, "speaking_rate", lambda *args: 210)
    monkeypatch.setattr(
        service,
        "model_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("A voice-only copy must not call the writer")
        ),
    )
    changed = ensure_daily(session, user.id)
    rows = service.segments_for(session, changed.id)
    assert sum(len(s.text.split()) for s in rows) > original_words
    assert changed.request["voice_detail_adjusted"] is True
    assert service.verified_script(session, rows)
    assert list(dict.fromkeys(s.story_id for s in rows if s.claim_ids)) == list(
        dict.fromkeys(s.story_id for s in original if s.claim_ids)
    )


def test_daily_length_adds_balanced_detail_instead_of_capping_at_two_facts(
    session, monkeypatch
):
    user = listener(session, "duration", "en", ["technology"])
    stories = [{"id": "story-" + str(i), "disagreements": []} for i in range(3)]
    facts = {
        story["id"]: [
            (
                {
                    "id": f"{story['id']}-fact-{i}",
                    "text": f"Company {story['id']} reported that project {i} opened a new regional research facility with additional engineering equipment and twenty permanent staff positions.",
                },
                [{"article_id": "source"}],
            )
            for i in range(20)
        ]
        for story in stories
    }
    monkeypatch.setattr(service, "recommendations", lambda *args, **kwargs: stories)
    monkeypatch.setattr(
        service,
        "story_detail",
        lambda db, sid: next(s for s in stories if s["id"] == sid),
    )
    monkeypatch.setattr(service, "eligible", lambda story, *args: facts[story["id"]])
    counts = []
    for minutes in (1, 3, 5):
        item = service.create_briefing(
            session, user.id, BriefingRequest(story_limit=3, duration_minutes=minutes)
        )
        chosen = service.draft_candidates(session, item)
        per_story = Counter(story["id"] for story, fact, citations in chosen.values())
        assert len(per_story) == 3
        assert max(per_story.values()) - min(per_story.values()) <= 1
        words = (
            sum(len(fact["text"].split()) for story, fact, citations in chosen.values())
            + 26
        )
        assert (
            item.request["target_words"] - 24 <= words <= item.request["target_words"]
        )
        assert [story["id"] for story, _, _ in chosen.values()] == sorted(
            story["id"] for story, _, _ in chosen.values()
        )
        counts.append(len(chosen))
    assert counts[1] > counts[0] * 2 and counts[2] > counts[1]
    set_preferences(session, user.id, {"depth": "brief"})
    item = service.create_briefing(
        session, user.id, BriefingRequest(story_limit=3, duration_minutes=3)
    )
    assert len(service.draft_candidates(session, item)) == counts[1]


def test_preference_change_replaces_daily_cache_but_voice_change_keeps_script(session):
    user = listener(session, "duration-cache", "en", ["technology"])
    set_preferences(session, user.id, {"duration_minutes": 3})
    first = ensure_daily(session, user.id)
    assert ensure_daily(session, user.id).id == first.id
    set_preferences(session, user.id, {"duration_minutes": 5})
    changed = ensure_daily(session, user.id)
    assert changed.id != first.id and changed.request["duration_minutes"] == 5
    service.generate_script(session, changed.id)
    service.synthesize_briefing(session, changed.id)
    set_preferences(
        session, user.id, {"voice_profile_id": "jarvis", "voice_engine": "elevenlabs"}
    )
    voice_version = ensure_daily(session, user.id)
    assert voice_version.id != changed.id
    assert voice_version.status == "script_ready"
    assert voice_version.request["source_briefing_id"] == changed.id
    prefs = preferences(session, user.id)
    assert (
        daily_key(user.id, prefs, date(2026, 11, 21))
        != f"daily/{user.id}/2026-11-21/top3"
    )


def test_rate_uses_real_audio_and_deduplicates_shared_template_copies(session):
    user = listener(session, "rate", "en", [])
    assert speaking_rate(session, "en", "professional") == 140
    for index, (words, seconds) in enumerate(((120, 60), (160, 60))):
        audio = GeneratedAudio(
            cache_key=str(index),
            object_key=str(index),
            duration_seconds=seconds,
            boundaries=[],
            provider="elevenlabs",
        )
        session.add(audio)
        session.flush()
        for copy in range(5 if index == 0 else 1):
            item = Briefing(
                user_id=user.id,
                title="Rate sample",
                status="completed",
                language="en",
                voice_profile_id="professional",
                request={"period": "day", "duration_minutes": 3},
                duration_seconds=seconds,
                audio_id=audio.id,
            )
            session.add(item)
            session.flush()
            session.add(
                BriefingSegment(
                    briefing_id=item.id,
                    position=0,
                    text="word " * words,
                    language="en",
                    claim_ids=[],
                    source_article_ids=[],
                    citations=[],
                    verification_status="editorial",
                )
            )
    session.flush()
    assert speaking_rate(session, "en", "professional") == 140


def test_short_editions_show_both_target_and_actual_duration(session):
    user = listener(session, "short-edition", "en", [])
    item = service.create_briefing(
        session, user.id, BriefingRequest(duration_minutes=3)
    )
    item.status, item.duration_seconds = "completed", 60
    view = service.briefing_view(session, item)
    assert view["target_duration_seconds"] == 180 and view["duration_seconds"] == 60
    assert view["duration_note"]
    item.duration_seconds = 175
    assert service.briefing_view(session, item)["duration_note"] is None
