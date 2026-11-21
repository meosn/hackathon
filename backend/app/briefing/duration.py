"""Plan spoken length from actual narration rates, without padding the evidence."""

from collections import defaultdict
from statistics import median

from sqlalchemy import select

from .models import Briefing, BriefingSegment

DEFAULT_WPM = {"en": 140, "de": 125, "nl": 135}


def speaking_rate(db, language, voice):
    editions = db.scalars(
        select(Briefing)
        .where(
            Briefing.status == "completed",
            Briefing.language == language,
            Briefing.voice_profile_id == voice,
            Briefing.duration_seconds >= 30,
            Briefing.audio_id.is_not(None),
        )
        .order_by(Briefing.created_at.desc())
        .limit(64)
    ).all()
    # Shared daily copies must not outweigh different real recordings.
    samples = {}
    for item in editions:
        samples.setdefault(item.audio_id, item)
        if len(samples) == 3:
            break
    if not samples:
        return DEFAULT_WPM.get(language, 140)
    words = defaultdict(int)
    for bid, text in db.execute(
        select(BriefingSegment.briefing_id, BriefingSegment.text).where(
            BriefingSegment.briefing_id.in_([item.id for item in samples.values()])
        )
    ):
        words[bid] += len(text.split())
    rates = [
        words[item.id] * 60 / item.duration_seconds
        for item in samples.values()
        if words[item.id]
    ]
    return (
        round(max(90, min(210, median(rates))))
        if rates
        else DEFAULT_WPM.get(language, 140)
    )
