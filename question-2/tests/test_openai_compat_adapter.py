"""OpenAI-compatible adapter against an in-process mock transport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.models.base import ModelError
from agent.models.openai_compat import OpenAICompatClient, from_wire, to_wire
from agent.types import Message, ToolCall, ToolSpec


def ok(message, prompt=100, completion=20):
    return httpx.Response(
        200, json={"choices": [{"message": message}], "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}
    )


def client(responses, **kw):
    seen, sleeps = [], []
    queue = list(responses)

    def handler(req):
        seen.append(json.loads(req.content))
        return queue.pop(0)

    c = OpenAICompatClient(
        "https://example.test/v1", "k", "m", transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw
    )
    return c, seen, sleeps


def test_wire_format_round_trip():
    msgs = [
        Message("system", "S"),
        Message("user", "q"),
        Message("assistant", "", tool_calls=(ToolCall("c1", "get_issue", '{"number": 3}'),)),
        Message("tool", "result", tool_call_id="c1", tool_name="get_issue"),
    ]
    wire = to_wire(msgs)
    assert [w["role"] for w in wire] == ["system", "user", "assistant", "tool"]
    assert wire[2]["tool_calls"][0]["function"] == {"name": "get_issue", "arguments": '{"number": 3}'}
    assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": "result"}


def test_tool_call_reply_keeps_raw_arguments():
    r = from_wire({"choices": [{"message": {"tool_calls": [
        {"id": "x", "type": "function", "function": {"name": "search_notes", "arguments": "{bad json"}}
    ]}}]})
    assert r.tool_calls[0].raw_args == "{bad json"  # malformed args reach our validator


def test_request_has_seed_temperature_tools():
    c, seen, _ = client([ok({"content": "hi"})], seed=7)
    assert c.complete([Message("user", "q")], [ToolSpec("t", "d", {"type": "object"})]).text == "hi"
    body = seen[0]
    assert body["seed"] == 7 and body["temperature"] == 0 and body["model"] == "m"
    assert body["tools"][0]["function"]["name"] == "t"


def test_429_waits_retry_after_then_succeeds():
    c, _, sleeps = client([httpx.Response(429, headers={"retry-after": "3"}), ok({"content": "ok"})])
    assert c.complete([Message("user", "q")], []).text == "ok"
    assert sleeps == [3.5]


def test_daily_quota_fails_fast():
    c, _, sleeps = client([httpx.Response(429, headers={"retry-after": "50000"})])
    with pytest.raises(ModelError, match="quota exhausted"):
        c.complete([Message("user", "q")], [])
    assert sleeps == []


def test_400_not_retried():
    c, _, sleeps = client([httpx.Response(400, json={"error": "bad"})])
    with pytest.raises(ModelError, match="400"):
        c.complete([Message("user", "q")], [])
    assert sleeps == []
