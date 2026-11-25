"""LLM providers with structured output.

Each provider takes a system prompt, a user prompt and a JSON schema, and returns
parsed JSON plus token usage. Claude uses tool use to force the schema; OpenAI
uses ``response_format={"type": "json_schema"}``. ``OfflineProvider`` returns
nothing, so the pipeline falls back to the deterministic analyzers alone. That is
what tests and the eval baseline use.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import Usage

FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "description": "Line number in the NEW file (left column)."},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "title": {"type": "string", "description": "Short title, under 8 words."},
                    "message": {"type": "string", "description": "What is wrong and why it matters, 1-3 sentences."},
                    "suggestion": {"type": "string", "description": "Concrete fix; code allowed."},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "confirms_rule": {"type": "string", "description": "Rule id from the hints this confirms, or empty."},
                },
                "required": ["line", "severity", "title", "message", "confidence"],
                "additionalProperties": False,
            },
        },
        "rejected_hints": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ids of static hints you judged to be false positives.",
        },
    },
    "required": ["findings"],
    "additionalProperties": False,
}


@dataclass
class LLMResponse:
    data: dict[str, Any]
    usage: Usage = field(default_factory=Usage)


class LLMProvider(Protocol):
    name: str

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse: ...


class OfflineProvider:
    """No model: the pipeline relies on deterministic analyzers only."""

    name = "offline"

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        return LLMResponse({"findings": [], "rejected_hints": []})


class ScriptedProvider:
    """Returns canned responses keyed by agent name. Used in tests."""

    name = "scripted"

    def __init__(self, responses: dict[str, dict[str, Any]], fail_times: int = 0):
        self.responses = responses
        self.fail_times = fail_times
        self.calls: list[str] = []

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        self.calls.append(system)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("simulated outage")
        agent = re.search(r"You are the (\w+) reviewer", system)
        data = self.responses.get(agent.group(1) if agent else "", {"findings": []})
        return LLMResponse(data, Usage(len(user) // 4, 50, 1))


class AnthropicProvider:
    def __init__(self, model: str | None = None, api_key: str | None = None, max_tokens: int = 2048):
        import httpx

        self.name = model or os.getenv("REVIEWPILOT_MODEL", "claude-sonnet-4-5")
        self.max_tokens = max_tokens
        self._http = httpx.AsyncClient(
            base_url="https://api.anthropic.com", timeout=90,
            headers={"x-api-key": api_key or os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01", "content-type": "application/json"},
        )

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        import httpx

        body = {
            "model": self.name, "max_tokens": self.max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": "report", "description": "Report review findings.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "report"},
        }
        try:
            r = await self._http.post("/v1/messages", json=body)
        except httpx.TransportError as e:
            raise ConnectionError(str(e)) from e
        if r.status_code in (429, 500, 502, 503, 529):
            raise ConnectionError(f"anthropic {r.status_code}")
        r.raise_for_status()
        d = r.json()
        block = next((b for b in d.get("content", []) if b.get("type") == "tool_use"), None)
        u = d.get("usage", {})
        return LLMResponse(block["input"] if block else {"findings": []},
                           Usage(u.get("input_tokens", 0), u.get("output_tokens", 0), 1))


class OpenAIProvider:
    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        import httpx

        self.name = model or os.getenv("REVIEWPILOT_MODEL", "gpt-4.1-mini")
        self._http = httpx.AsyncClient(
            base_url=base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"), timeout=90,
            headers={"authorization": f"Bearer {api_key or os.environ['OPENAI_API_KEY']}"},
        )

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        import httpx

        body = {
            "model": self.name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "report", "schema": schema, "strict": False}},
        }
        try:
            r = await self._http.post("/chat/completions", json=body)
        except httpx.TransportError as e:
            raise ConnectionError(str(e)) from e
        if r.status_code in (429, 500, 502, 503):
            raise ConnectionError(f"openai {r.status_code}")
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        return LLMResponse(parse_json(d["choices"][0]["message"]["content"]),
                           Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0), 1))


class CachedProvider:
    """Memoises responses by prompt hash so re-reviewing an unchanged diff is free."""

    def __init__(self, inner: LLMProvider, maxsize: int = 512):
        self.inner = inner
        self.name = inner.name
        self._cache: dict[str, LLMResponse] = {}
        self.maxsize = maxsize
        self.hits = 0

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        key = hashlib.sha256(f"{self.name}\0{system}\0{user}".encode()).hexdigest()
        if key in self._cache:
            self.hits += 1
            return LLMResponse(self._cache[key].data, Usage())
        resp = await self.inner.complete_json(system, user, schema)
        if len(self._cache) >= self.maxsize:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = resp
        return resp


def parse_json(text: str) -> dict[str, Any]:
    """Parse model output that should be JSON, tolerating code fences and stray prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def provider_from_env() -> LLMProvider:
    kind = os.getenv("REVIEWPILOT_PROVIDER", "").lower()
    if kind == "anthropic" or (not kind and os.getenv("ANTHROPIC_API_KEY")):
        return CachedProvider(AnthropicProvider())
    if kind == "openai" or (not kind and os.getenv("OPENAI_API_KEY")):
        return CachedProvider(OpenAIProvider())
    return OfflineProvider()
