"""Gemini adapter (google-genai SDK, raw calls only; automatic function calling off).

Translation rules:
- system messages -> system_instruction
- assistant messages -> role "model"; if the reply came from Gemini, its original
  Content is echoed back verbatim (provider_data) so thought signatures survive
- consecutive tool messages -> one role "user" Content of function_response parts
- usage: output tokens include thinking tokens (billed as output)
Rate limits: the free tier allows 5 requests/minute (seen as a 429). The client paces
itself to `rpm` and, on 429, waits the server's suggested retry delay. 5xx gets
exponential backoff. Anything else becomes ModelError.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

from agent.models.base import ModelError
from agent.types import Message, ModelReply, ToolCall, ToolSpec, Usage

RETRYABLE = {429, 500, 502, 503, 504}
MAX_WAIT_S = 60.0  # a longer suggested wait means a daily quota is exhausted: fail fast
_RETRY_IN = re.compile(r"retry in ([0-9.]+)s", re.I)


def retry_delay(e: Any, attempt: int) -> float:
    """Server-suggested delay (RetryInfo or message text), else exponential backoff."""
    details = getattr(e, "details", None) or {}
    for d in (details.get("error", {}) if isinstance(details, dict) else {}).get("details", []) or []:
        if isinstance(d, dict) and str(d.get("retryDelay", "")).endswith("s"):
            try:
                return float(d["retryDelay"][:-1]) + 1.0
            except ValueError:
                pass
    m = _RETRY_IN.search(str(getattr(e, "message", "") or ""))
    if m:
        return float(m.group(1)) + 1.0
    return 2.0 * 2**attempt  # 2, 4, 8, 16 s
_GEN_ID = "gc_"  # prefix for ids we invent when Gemini sends none


def _types():
    from google.genai import types

    return types


def to_contents(messages: Sequence[Message]) -> tuple[str, list[Any]]:
    types = _types()
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    contents: list[Any] = []
    pending_responses: list[Any] = []

    def flush() -> None:
        if pending_responses:
            contents.append(types.Content(role="user", parts=list(pending_responses)))
            pending_responses.clear()

    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            fr = types.FunctionResponse(name=m.tool_name or "", response={"result": m.content})
            if m.tool_call_id and not m.tool_call_id.startswith(_GEN_ID):
                fr.id = m.tool_call_id
            pending_responses.append(types.Part(function_response=fr))
            continue
        flush()
        if m.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m.content)]))
        elif m.provider_data is not None:
            contents.append(m.provider_data)
        else:
            parts = [types.Part(text=m.content)] if m.content else []
            for c in m.tool_calls:
                try:
                    args = json.loads(c.raw_args or "{}")
                except json.JSONDecodeError:
                    args = {"_unparsed": c.raw_args}
                fc = types.FunctionCall(name=c.name, args=args if isinstance(args, dict) else {"_value": args})
                if not c.id.startswith(_GEN_ID):
                    fc.id = c.id
                parts.append(types.Part(function_call=fc))
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
    flush()
    return system, contents


def to_declarations(tools: Sequence[ToolSpec]) -> list[Any]:
    types = _types()
    return [
        types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
        for t in tools
    ]


def from_response(resp: Any) -> ModelReply:
    cands = getattr(resp, "candidates", None) or []
    if not cands or cands[0].content is None:
        feedback = getattr(resp, "prompt_feedback", None)
        raise ModelError(f"Gemini returned no candidate (prompt_feedback={feedback})")
    content = cands[0].content
    texts, calls = [], []
    for i, part in enumerate(content.parts or []):
        if part.function_call is not None:
            fc = part.function_call
            calls.append(
                ToolCall(id=fc.id or f"{_GEN_ID}{i}", name=fc.name or "", raw_args=json.dumps(fc.args or {}))
            )
        elif part.text and not part.thought:
            texts.append(part.text)
    um = getattr(resp, "usage_metadata", None)
    usage = Usage(
        input_tokens=(um.prompt_token_count or 0) if um else 0,
        output_tokens=((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0,
    )
    return ModelReply(text="".join(texts).strip(), tool_calls=tuple(calls), usage=usage, provider_data=content)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        *,
        seed: int = 42,
        temperature: float = 0.0,
        thinking_level: str = "LOW",
        timeout_s: float = 60.0,
        max_retries: int = 4,
        rpm: float = 0,  # client-side pacing; 0 = off. Free tier: 5
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        client: Any = None,
    ) -> None:
        types = _types()
        if client is None:
            if not api_key:
                raise ValueError("GEMINI_API_KEY is empty")
            from google import genai

            client = genai.Client(
                api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000))
            )
        self._client = client
        self.model_name = model_name
        self._seed, self._temperature, self._thinking = seed, temperature, thinking_level
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
        types = _types()
        system, contents = to_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=[types.Tool(function_declarations=to_declarations(tools))] if tools else None,
            temperature=self._temperature,
            seed=self._seed,
            thinking_config=types.ThinkingConfig(thinking_level=self._thinking),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self._call_with_retries(
            lambda: self._client.models.generate_content(model=self.model_name, contents=contents, config=config)
        )
        return from_response(resp)

    def _call_with_retries(self, fn: Callable[[], Any]) -> Any:
        from google.genai import errors

        for attempt in range(self._max_retries + 1):
            self._pace()
            try:
                return fn()
            except errors.APIError as e:
                if e.code in RETRYABLE and attempt < self._max_retries:
                    wait = retry_delay(e, attempt)
                    if wait > MAX_WAIT_S:
                        raise ModelError(f"Gemini quota exhausted (retry in {wait:.0f}s): {e.message}") from e
                    self._sleep(wait)
                    continue
                raise ModelError(f"Gemini API error {e.code}: {e.message}") from e
        raise AssertionError("unreachable")
