"""Contract every ModelClient adapter must meet, run against each adapter.

Each adapter is driven by canned provider responses for two scenarios ("call a tool",
"answer in text") and must produce equivalent ModelReply objects and work inside the
real agent loop. A new adapter (Anthropic, Ollama) is added by extending ADAPTERS.
"""

from __future__ import annotations

import json

import pytest
from google.genai import types

from agent.loop import Agent, StopReason
from agent.models.fake import FakeModelClient, call, text_reply, tool_reply
from agent.models.gemini import GeminiClient
from agent.models.pricing import price_for
from agent.trace import read_trace


def _gemini_resp(part):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20),
    )


class _Stub:
    def __init__(self, results):
        self.models = self
        self._results = list(results)

    def generate_content(self, **_kw):
        return self._results.pop(0)


def fake_adapter():
    return FakeModelClient([tool_reply(call("echo", {"text": "hi"})), text_reply("done")])


def gemini_adapter():
    return GeminiClient(
        "",
        "gemini-3.5-flash",
        client=_Stub(
            [
                _gemini_resp(types.Part(function_call=types.FunctionCall(name="echo", args={"text": "hi"}))),
                _gemini_resp(types.Part(text="done")),
            ]
        ),
    )


def openai_compat_adapter():
    import httpx

    from agent.models.openai_compat import OpenAICompatClient

    replies = [
        {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "echo", "arguments": '{"text": "hi"}'}}]},
        {"content": "done"},
    ]

    def handler(_req):
        return httpx.Response(200, json={"choices": [{"message": replies.pop(0)}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    return OpenAICompatClient("https://x.test/v1", "k", "openai/gpt-4o-mini", transport=httpx.MockTransport(handler))


ADAPTERS = {"fake": fake_adapter, "gemini": gemini_adapter, "openai_compat": openai_compat_adapter}


@pytest.mark.parametrize("name", ADAPTERS)
def test_adapter_runs_tool_then_answers_inside_the_loop(name, registry, tmp_path):
    model = ADAPTERS[name]()
    agent = Agent(model, registry, price=price_for(model.model_name), trace_dir=tmp_path)
    r = agent.run("say hi")
    assert r.stop_reason is StopReason.FINAL and r.answer == "done"
    calls = [e for e in read_trace(r.trace_path) if e["event"] == "tool_call"]
    assert [(c["tool"], json.loads(c["args"]), c["ok"]) for c in calls] == [("echo", {"text": "hi"}, True)]
    models = [e for e in read_trace(r.trace_path) if e["event"] == "model_call"]
    assert all(m["input_tokens"] == 100 and m["output_tokens"] == 20 and m["cost_usd"] > 0 for m in models)
