"""Gemini adapter, offline: message translation, response parsing, retries.

A stub stands in for the SDK client, so this proves the translation layer, not that
Gemini accepts the request (the real-mode smoke run covers that).
"""

from __future__ import annotations

import json

import pytest
from google.genai import errors, types

from agent.models.base import ModelError
from agent.models.gemini import GeminiClient, from_response, to_contents, to_declarations
from agent.types import Message, ToolCall, ToolSpec


def response(*parts, prompt=10, out=5, thoughts=7):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
        ),
    )


class StubModels:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def generate_content(self, *, model, contents, config):
        self.requests.append((model, contents, config))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class StubClient:
    def __init__(self, results):
        self.models = StubModels(results)


def client(results, **kw):
    sleeps = []
    c = GeminiClient("", "gemini-3.5-flash", client=StubClient(results), sleep=sleeps.append, **kw)
    return c, sleeps


# -- request translation ---------------------------------------------------------


def test_system_goes_to_system_instruction_and_tool_results_are_grouped():
    msgs = [
        Message("system", "be safe"),
        Message("user", "hi"),
        Message("assistant", "", tool_calls=(ToolCall("gc_0", "a", '{"x":1}'), ToolCall("id9", "b", "{}"))),
        Message("tool", "ra", tool_call_id="gc_0", tool_name="a"),
        Message("tool", "rb", tool_call_id="id9", tool_name="b"),
    ]
    system, contents = to_contents(msgs)
    assert system == "be safe"
    assert [c.role for c in contents] == ["user", "model", "user"]
    fcs = [p.function_call for p in contents[1].parts]
    assert [(f.name, f.args, f.id) for f in fcs] == [("a", {"x": 1}, None), ("b", {}, "id9")]
    frs = [p.function_response for p in contents[2].parts]
    assert [(f.name, f.response, f.id) for f in frs] == [("a", {"result": "ra"}, None), ("b", {"result": "rb"}, "id9")]


def test_gemini_content_is_echoed_back_verbatim():
    original = types.Content(role="model", parts=[types.Part(text="x", thought_signature=b"sig")])
    _, contents = to_contents([Message("user", "q"), Message("assistant", "x", provider_data=original)])
    assert contents[1] is original


def test_declarations_carry_json_schema():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    (d,) = to_declarations([ToolSpec("search", "find", schema)])
    assert (d.name, d.description, d.parameters_json_schema) == ("search", "find", schema)


# -- response parsing ------------------------------------------------------------


def test_text_reply_skips_thoughts_and_counts_thinking_as_output():
    r = from_response(response(types.Part(text="hmm", thought=True), types.Part(text="Answer.")))
    assert r.text == "Answer." and r.tool_calls == ()
    assert (r.usage.input_tokens, r.usage.output_tokens) == (10, 12)


def test_function_call_reply():
    r = from_response(response(types.Part(function_call=types.FunctionCall(name="get_issue", args={"number": 3}))))
    (call,) = r.tool_calls
    assert call.name == "get_issue" and json.loads(call.raw_args) == {"number": 3}
    assert call.id.startswith("gc_")
    assert r.provider_data.parts[0].function_call.name == "get_issue"


def test_no_candidate_is_a_model_error():
    with pytest.raises(ModelError):
        from_response(types.GenerateContentResponse(candidates=[]))


# -- calls + retries -----------------------------------------------------------------


def test_complete_sends_config_and_tools():
    c, _ = client([response(types.Part(text="ok"))], seed=7)
    reply = c.complete([Message("system", "S"), Message("user", "q")], [ToolSpec("t", "d", {"type": "object"})])
    assert reply.text == "ok"
    model, contents, config = c._client.models.requests[0]
    assert model == "gemini-3.5-flash"
    assert config.system_instruction == "S" and config.seed == 7 and config.temperature == 0
    assert config.automatic_function_calling.disable is True
    assert config.tools[0].function_declarations[0].name == "t"


def api_error(code):
    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "S"}})


def test_retries_rate_limit_then_succeeds():
    c, sleeps = client([api_error(429), api_error(503), response(types.Part(text="ok"))])
    assert c.complete([Message("user", "q")], []).text == "ok"
    assert sleeps == [2.0, 4.0]


def test_gives_up_after_max_retries():
    c, sleeps = client([api_error(429)] * 3, max_retries=2)
    with pytest.raises(ModelError, match="429"):
        c.complete([Message("user", "q")], [])
    assert len(sleeps) == 2


def test_client_errors_are_not_retried():
    c, sleeps = client([api_error(400)])
    with pytest.raises(ModelError, match="400"):
        c.complete([Message("user", "q")], [])
    assert sleeps == []


def test_rate_limit_waits_the_server_suggested_delay():
    e = errors.APIError(429, {"error": {"code": 429, "message": "Quota exceeded. Please retry in 25.8s.", "status": "RESOURCE_EXHAUSTED"}})
    c, sleeps = client([e, response(types.Part(text="ok"))])
    c.complete([Message("user", "q")], [])
    assert sleeps == [pytest.approx(26.8)]


def test_retry_info_detail_wins():
    e = errors.APIError(
        429,
        {"error": {"code": 429, "message": "x", "status": "S",
                   "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]}},
    )
    c, sleeps = client([e, response(types.Part(text="ok"))])
    c.complete([Message("user", "q")], [])
    assert sleeps == [13.0]


def test_client_side_pacing_spaces_calls():
    now = [100.0]
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    c = GeminiClient(
        "", "gemini-3.5-flash", rpm=5, sleep=sleep, clock=lambda: now[0],
        client=StubClient([response(types.Part(text="a")), response(types.Part(text="b"))]),
    )
    c.complete([Message("user", "q")], [])
    now[0] += 2.0  # next call 2 s later
    c.complete([Message("user", "q")], [])
    assert sleeps == [pytest.approx(10.0)]  # 60/5 = 12 s spacing
