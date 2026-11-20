from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException

from app.briefing import agent_setup, realtime, research
from app.briefing.contracts import ResearchRequest
from app.briefing.models import Conversation, ConversationMessage
from app.db import utcnow
from test_listener_workflow import session, listener
from test_briefing_http import api


def conversation(db, name="research"):
    user = listener(db, name, "en", ["technology"])
    conv = Conversation(user_id=user.id, language="en")
    db.add(conv)
    db.commit()
    return conv


def provider_result(url="https://science.nasa.gov/mars/"):
    return {
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 25},
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Mars has two moons.\ue200cite\ue202turn0search0\ue201",
                        "annotations": [
                            {"type": "url_citation", "url": url, "title": "NASA: Mars"}
                        ],
                    }
                ],
            },
        ],
    }


def test_offer_consent_and_cancellation_do_not_search(session, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_RESEARCH_ENABLED", "1")
    monkeypatch.setattr(research, "search_web", lambda *args: pytest.fail("No consent"))
    conv = conversation(session)
    result = research.handle(
        session,
        conv,
        ResearchRequest(action="offer", query="How many moons does Mars have?"),
    )
    assert result.status == "offered" and not result.sources
    assert "Ask whether" in result.answer
    assert (
        research.handle(session, conv, ResearchRequest(action="cancel")).status
        == "cancelled"
    )
    with pytest.raises(HTTPException) as failure:
        research.handle(session, conv, ResearchRequest(action="search"))
    assert failure.value.status_code == 409


def test_confirmed_search_remembers_topic_and_requires_cited_web_results(
    session, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_RESEARCH_ENABLED", "1")
    query = "Сколько спутников у Марса?"
    calls = []

    def provider(url, **kwargs):
        calls.append(kwargs["json"])
        assert url == "https://api.openai.com/v1/responses"
        assert kwargs["json"]["input"] == query
        assert kwargs["json"]["tools"][0]["type"] == "web_search"
        assert kwargs["json"]["tool_choice"] == "required"
        assert kwargs["json"]["store"] is False
        return httpx.Response(
            200, request=httpx.Request("POST", url), json=provider_result()
        )

    monkeypatch.setattr(research.httpx, "post", provider)
    conv = conversation(session)
    research.handle(session, conv, ResearchRequest(action="offer", query=query))
    assert not calls
    result = research.handle(
        session, conv, ResearchRequest(action="search", query="Yes")
    )
    assert len(calls) == 1 and result.status == "completed"
    assert result.query == query and result.answer == "Mars has two moons."
    assert result.outside_briefing and result.checked_at
    assert result.sources[0].url == "https://science.nasa.gov/mars/"
    with pytest.raises(HTTPException):
        research.handle(session, conv, ResearchRequest(action="search"))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "bad_result",
    [
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "An uncited guess."}],
                }
            ],
        },
        provider_result("javascript:alert(1)"),
        {**provider_result(), "status": "incomplete"},
    ],
)
def test_no_fake_findings_when_search_is_incomplete_or_uncited(
    session, monkeypatch, bad_result
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_RESEARCH_ENABLED", "1")
    monkeypatch.setattr(
        research.httpx,
        "post",
        lambda url, **kwargs: httpx.Response(
            200, request=httpx.Request("POST", url), json=bad_result
        ),
    )
    conv = conversation(session)
    research.handle(session, conv, ResearchRequest(action="offer", query="Mars moons"))
    result = research.handle(session, conv, ResearchRequest(action="search"))
    assert result.status == "unavailable" and not result.sources
    assert "did not succeed" in result.answer


def test_expired_offer_and_another_conversation_cannot_supply_consent(
    session, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        research, "search_web", lambda *args: pytest.fail("No active consent")
    )
    first, second = conversation(session), conversation(session, "other-research")
    research.handle(session, first, ResearchRequest(action="offer", query="Mars moons"))
    with pytest.raises(HTTPException):
        research.handle(session, second, ResearchRequest(action="search"))
    pending = (
        session.query(ConversationMessage).filter_by(conversation_id=first.id).one()
    )
    pending.created_at = utcnow() - timedelta(minutes=16)
    session.commit()
    with pytest.raises(HTTPException):
        research.handle(session, first, ResearchRequest(action="search"))


def test_research_http_is_owner_scoped(api, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_RESEARCH_ENABLED", "1")
    tokens = [
        api.post("/api/v1/auth/demo", json={"profile": profile}).json()["access_token"]
        for profile in ("tech", "finance")
    ]
    headers, other = [{"Authorization": "Bearer " + token} for token in tokens]
    conv = api.post("/api/v1/conversations", headers=headers, json={}).json()
    path = "/api/v1/conversations/" + conv["id"] + "/research"
    assert (
        api.post(
            path, headers=other, json={"action": "offer", "query": "Mars moons"}
        ).status_code
        == 404
    )
    assert api.post(path, headers=headers, json={"action": "search"}).status_code == 409
    result = api.post(
        path, headers=headers, json={"action": "offer", "query": "Mars moons"}
    )
    assert result.status_code == 200 and result.json()["status"] == "offered"


def test_both_voice_engines_can_offer_and_perform_research():
    native = realtime.session_config("en", [], speech_stream=False)
    eleven = agent_setup.configuration()["conversation_config"]["agent"]["prompt"]
    for prompt, tools in (
        (native["instructions"], native["tools"]),
        (eleven["prompt"], eleven["tools"]),
    ):
        assert "Never refuse merely because" in prompt
        assert "including just 'да'" in prompt
        tool = next(tool for tool in tools if tool["name"] == "research_topic")
        assert tool["parameters"]["properties"]["action"]["enum"] == [
            "offer",
            "search",
            "cancel",
        ]
        assert tool["parameters"]["properties"]["action"]["description"]
    assert "additionalProperties" not in eleven["tools"][-1]["parameters"]
