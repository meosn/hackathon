"""Structured model adapters. Only allowlisted claim IDs reach the final script."""

import asyncio
import json
import os
from time import monotonic
from typing import Protocol

import httpx
from pydantic import BaseModel

from .accounting import observe
from .contracts import Decision, Script


class LLMProvider(Protocol):
    async def generate_structured(
        self, messages: list[dict], schema: type[BaseModel]
    ) -> BaseModel: ...


class MockProvider:
    async def generate_structured(self, messages, schema):
        if schema is Decision:
            return Decision(intent="FOLLOW_UP")
        candidates = json.loads(messages[-1]["content"])
        return Script(lines=candidates)


class RemoteProvider:
    def __init__(self, db, reference_id, provider):
        self.db = db
        self.reference_id = reference_id
        self.provider = provider

    async def generate_structured(self, messages, schema, *, model=None, timeout=None):
        local = self.provider == "ollama"
        default_url = "http://localhost:11434" if local else "https://api.openai.com/v1"
        base = (os.getenv("LOCAL_LLM_BASE_URL") or (os.getenv("LLM_BASE_URL") if os.getenv("LLM_PROVIDER") == "ollama" else None) or default_url) if local else (os.getenv("LLM_BASE_URL") or default_url)
        model = (
            model or os.getenv("LLM_MODEL") or ("llama3.2" if local else "gpt-4o-mini")
        )
        headers = {}
        if not local and (key := os.getenv("LLM_API_KEY")):
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "messages": messages, "stream": False}
        if local:
            body.update(
                format=schema.model_json_schema(),
                options={"temperature": 0, "num_ctx": 4096, "num_predict": 768, "num_thread": 2},
                think=False,
                keep_alive="10m",
            )
        else:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                },
            }
        start = monotonic()
        input_count = output_count = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    timeout or float(os.getenv("LLM_TIMEOUT_SECONDS", "180")), connect=5
                )
            ) as client:
                response = await client.post(
                    base.rstrip("/") + ("/api/chat" if local else "/chat/completions"),
                    json=body,
                    headers=headers,
                )
            response.raise_for_status()
            result = response.json()
            usage = result.get("usage", {})
            input_count = result.get("prompt_eval_count", usage.get("prompt_tokens", 0))
            output_count = result.get("eval_count", usage.get("completion_tokens", 0))
            message = result["message"] if local else result["choices"][0]["message"]
            return schema.model_validate_json(message["content"])
        finally:
            observe(
                self.db,
                "llm",
                model,
                input_tokens=input_count,
                output_tokens=output_count,
                seconds=monotonic() - start,
                reference_id=self.reference_id,
                measured_usd=0 if local else None,
                scope=(
                    "dataset"
                    if _dataset_reference(self.db, self.reference_id)
                    else "listener"
                ),
            )


def model_output(db, reference_id, messages, schema, *, model=None, timeout=None):
    kind = os.getenv("LLM_PROVIDER", "mock")
    from .models import Briefing, Conversation
    from app.accounts import preferences
    briefing = db.get(Briefing, reference_id)
    conversation = db.get(Conversation, reference_id) if not briefing else None
    local_choice = (briefing and briefing.request.get("discussion_model") == "local") or (conversation and preferences(db, conversation.user_id)["discussion_model"] == "local")
    if local_choice:
        if os.getenv("LOCAL_LLM_ENABLED", "0") != "1":
            raise ValueError("The local model is unavailable")
        kind, model = "ollama", os.getenv("LOCAL_LLM_MODEL", "qwen3:0.6b")
        timeout = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "35"))
    if kind == "mock":
        return asyncio.run(MockProvider().generate_structured(messages, schema))
    if kind not in {"ollama", "api"}:
        raise ValueError("Unknown LLM provider")
    return asyncio.run(
        RemoteProvider(db, reference_id, kind).generate_structured(
            messages, schema, model=model, timeout=timeout
        )
    )


def _dataset_reference(db, reference_id):
    from app.news.models import IngestionJob, Story

    return bool(db.get(IngestionJob, reference_id) or db.get(Story, reference_id))
