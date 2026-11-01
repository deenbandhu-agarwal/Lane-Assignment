"""Required test 6: every run produces a full trace (prompt, tool call, result, latency, tokens, cost per step)."""

from __future__ import annotations

import itertools

import pytest

from agent.budget import Limits
from agent.loop import StopReason
from agent.models.fake import call, text_reply, tool_reply
from agent.trace import read_trace


def test_trace_has_every_step(make_agent):
    agent = make_agent([tool_reply(call("echo", {"text": "a"})), text_reply("done")])
    r = agent.run("question")
    events = read_trace(r.trace_path)
    kinds = [e["event"] for e in events]
    assert kinds == ["run_start", "model_call", "tool_call", "model_call", "citations", "run_end"]

    start, m1, tool, m2, _cites, end = events
    assert start["user_input"] == "question"
    for m in (m1, m2):
        assert m["prompt"] and m["latency_ms"] >= 0
        assert m["input_tokens"] == 100 and m["output_tokens"] == 20
        assert m["cost_usd"] > 0
    assert tool["tool"] == "echo" and tool["ok"] is True and '"echo"' in tool["result"]
    assert end["stop_reason"] == "final" and end["cost_usd"] == pytest.approx(r.cost_usd)
    assert len({e["run_id"] for e in events}) == 1


@pytest.mark.parametrize(
    "script, limits, reason",
    [
        ((tool_reply(call("echo", {"text": f"{i}"})) for i in itertools.count()), Limits(max_steps=2), "max_steps"),
        (itertools.repeat(tool_reply(call("echo", {"text": "x"}))), Limits(), "loop_detected"),
    ],
)
def test_trace_written_whatever_the_stop_reason(make_agent, script, limits, reason):
    r = make_agent(script, limits=limits).run("go")
    events = read_trace(r.trace_path)
    assert events[0]["event"] == "run_start"
    assert events[-1]["event"] == "run_end" and events[-1]["stop_reason"] == reason


def test_trace_written_on_model_error(make_agent):
    def boom(_):
        raise RuntimeError("down")

    r = make_agent([boom]).run("go")
    assert r.stop_reason is StopReason.MODEL_ERROR
    kinds = [e["event"] for e in read_trace(r.trace_path)]
    assert kinds == ["run_start", "model_error", "run_end"]


def test_each_run_gets_its_own_trace(make_agent):
    a = make_agent([text_reply("1")]).run("x")
    b = make_agent([text_reply("2")]).run("y")
    assert a.trace_path != b.trace_path
