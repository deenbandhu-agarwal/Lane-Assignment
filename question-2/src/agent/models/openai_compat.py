"""OpenAI-compatible Chat Completions adapter over raw HTTP (httpx, no SDK).

One adapter for every provider that speaks this API: GitHub Models, Groq, OpenRouter,
Ollama (http://localhost:11434/v1), OpenAI itself. Chosen by MODEL_BASE_URL.

Same policy as the Gemini adapter: client-side pacing to `rpm`; 429 waits Retry-After
unless it is longer than MAX_WAIT_S (a daily quota), which fails fast; 5xx backs off.
A 400 "output_parse_failed" (Groq: the model produced an unparseable tool call) is
re-sampled at RESAMPLE_TEMPERATURE without the seed (a deterministic retry repeats the
same bad output); any other 400 fails at once. Such a run is no longer exactly repeatable.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from agent.models.base import ModelError
from agent.types import Message, ModelReply, ToolCall, ToolSpec, Usage

RETRYABLE = {429, 500, 502, 503, 504}
MAX_WAIT_S = 60.0
# Groq 400 codes that mean "this sample was bad", not "this request was bad":
# output_parse_failed (unparseable tool call), tool_use_failed (Groq validated the call
# against the schema server-side and rejected it, e.g. k=20 over maximum 10).
BAD_SAMPLE_CODES = {"output_parse_failed", "tool_use_failed"}
RESAMPLE_TEMPERATURE = 0.7  # only used to retry an output_parse_failed reply


def to_wire(messages: Sequence[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_args}}
                        for c in m.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in tools
    ]


def from_wire(body: dict[str, Any]) -> ModelReply:
    choices = body.get("choices") or []
    if not choices:
        raise ModelError(f"no choices in response: {str(body)[:200]}")
    msg = choices[0].get("message") or {}
    calls = tuple(
        ToolCall(
            id=c.get("id") or f"call_{i}",
            name=(c.get("function") or {}).get("name", ""),
            raw_args=(c.get("function") or {}).get("arguments") or "{}",
        )
        for i, c in enumerate(msg.get("tool_calls") or [])
    )
    u = body.get("usage") or {}
    return ModelReply(
        text=(msg.get("content") or "").strip(),
        tool_calls=calls,
        usage=Usage(int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)),
    )


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        *,
        seed: int = 42,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        rpm: float = 0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("MODEL_BASE_URL is empty")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport)
        self.model_name = model_name
        self._seed, self._temperature = seed, temperature
        self._max_retries, self._sleep, self._clock = max_retries, sleep, clock
        self._min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._last_call: float | None = None

    def _pace(self) -> None:
        if self._min_interval and self._last_call is not None:
            wait = self._last_call + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": to_wire(messages),
            "temperature": self._temperature,
            "seed": self._seed,
        }
        if tools:
            payload["tools"] = to_tools(tools)
        for attempt in range(self._max_retries + 1):
            self._pace()
            try:
                r = self._http.post("/chat/completions", json=payload)
            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    self._sleep(2.0 * 2**attempt)
                    continue
                raise ModelError(f"HTTP error: {type(e).__name__}") from e
            if r.status_code == 200:
                return from_wire(r.json())
            if _is_parse_failure(r) and attempt < self._max_retries:
                # The model emitted an unparseable tool call. At temperature 0 with a fixed
                # seed the same request reproduces it (eval run 3, u3), so re-sample warmer.
                payload["temperature"] = RESAMPLE_TEMPERATURE
                payload.pop("seed", None)
                continue
            if r.status_code in RETRYABLE and attempt < self._max_retries:
                wait = _retry_after(r, attempt)
                if wait > MAX_WAIT_S:
                    raise ModelError(f"quota exhausted (retry in {wait:.0f}s): {r.text[:200]}")
                self._sleep(wait)
                continue
            raise ModelError(f"provider returned {r.status_code}: {r.text[:300]}")
        raise AssertionError("unreachable")


def _is_parse_failure(r: httpx.Response) -> bool:
    """Groq returns these 400s when the model's tool call is malformed. It is a bad
    sample, not a bad request, so it is re-sampled (no wait)."""
    if r.status_code != 400:
        return False
    try:
        err = r.json().get("error")
    except (ValueError, AttributeError):
        return False
    return isinstance(err, dict) and err.get("code") in BAD_SAMPLE_CODES


def _retry_after(r: httpx.Response, attempt: int) -> float:
    try:
        return float(r.headers["retry-after"]) + 0.5
    except (KeyError, ValueError):
        return 2.0 * 2**attempt
