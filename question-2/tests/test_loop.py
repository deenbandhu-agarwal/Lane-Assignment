"""Required test 4: the loop terminates on a looping / runaway model and on step / cost limits."""

from __future__ import annotations

import itertools

from agent.budget import Limits
from agent.loop import StopReason
from agent.models.fake import call, text_reply, tool_reply
from agent.types import Usage


def test_final_answer_in_one_step(make_agent):
    r = make_agent([text_reply("hello")]).run("hi")
    assert (r.stop_reason, r.answer, r.steps) == (StopReason.FINAL, "hello", 1)


def test_tool_result_is_fed_back_to_model(make_agent):
    agent = make_agent([tool_reply(call("echo", {"text": "ab", "times": 2})), text_reply("done")])
    r = agent.run("go")
    assert r.stop_reason is StopReason.FINAL
    tool_msg = agent.model.calls[1][-1]
    assert tool_msg.role == "tool" and '"echo": "abab"' in tool_msg.content


def test_runaway_model_stops_at_step_limit(make_agent):
    # Never answers; every call has different args so loop detection does not fire.
    runaway = (tool_reply(call("echo", {"text": f"x{i}"})) for i in itertools.count())
    r = make_agent(runaway, limits=Limits(max_steps=5)).run("go")
    assert r.stop_reason is StopReason.MAX_STEPS
    assert r.steps == 5


def test_identical_repeated_call_is_detected_as_loop(make_agent):
    same = itertools.repeat(tool_reply(call("echo", {"text": "x"})))
    r = make_agent(same, limits=Limits(max_steps=10, max_repeat_calls=3)).run("go")
    assert r.stop_reason is StopReason.LOOP
    assert r.steps == 3


def test_loop_detection_ignores_json_key_order(make_agent):
    script = [
        tool_reply(call("echo", '{"text": "x", "times": 1}')),
        tool_reply(call("echo", '{"times": 1, "text": "x"}')),
        tool_reply(call("echo", '{"text":"x","times":1}')),
    ]
    r = make_agent(script, limits=Limits(max_repeat_calls=3)).run("go")
    assert r.stop_reason is StopReason.LOOP


def test_cost_cap_stops_before_crossing(make_agent):
    # fake price: $1 / Mtok in -> 1M input tokens = $1.00 per call.
    expensive = Usage(input_tokens=1_000_000, output_tokens=0)
    runaway = (tool_reply(call("echo", {"text": f"x{i}"}), usage=expensive) for i in itertools.count())
    r = make_agent(runaway, limits=Limits(max_steps=50, max_cost_usd=3.5)).run("go")
    assert r.stop_reason is StopReason.MAX_COST
    assert r.cost_usd <= 3.5
    assert r.steps == 3  # $3 spent; a 4th call (~$1) would cross $3.50


def test_slow_model_times_out(make_agent):
    r = make_agent([text_reply("late")], delay_s=0.5, limits=Limits(step_timeout_s=0.05)).run("go")
    assert r.stop_reason is StopReason.TIMEOUT


def test_model_exception_stops_cleanly(make_agent):
    def boom(_messages):
        raise RuntimeError("provider down")

    r = make_agent([boom]).run("go")
    assert r.stop_reason is StopReason.MODEL_ERROR


def test_malformed_call_is_returned_and_model_can_recover(make_agent):
    agent = make_agent([tool_reply(call("echo", "{not json")), text_reply("fixed")])
    r = agent.run("go")
    assert r.stop_reason is StopReason.FINAL
    assert '"invalid_json"' in agent.model.calls[1][-1].content


def test_persistent_malformed_calls_stop(make_agent):
    bad = (tool_reply(call("echo", {"wrong": i})) for i in itertools.count())
    r = make_agent(bad, limits=Limits(max_malformed_steps=3)).run("go")
    assert r.stop_reason is StopReason.MALFORMED
    assert r.steps == 3
