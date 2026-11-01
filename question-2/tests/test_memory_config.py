"""Conversation memory (truncation) and .env loading."""

from __future__ import annotations

import os

from agent.config import Settings, load_dotenv
from agent.memory import Memory
from agent.models.fake import call, text_reply, tool_reply
from agent.types import Message, ToolCall


def turn(i: int, tool_output: str = "x" * 1000) -> list[Message]:
    c = ToolCall(f"c{i}", "search_notes", "{}")
    return [
        Message("user", f"q{i}"),
        Message("assistant", "", tool_calls=(c,)),
        Message("tool", tool_output, tool_call_id=c.id, tool_name="search_notes"),
        Message("assistant", f"a{i}"),
    ]


def test_keeps_only_last_turns():
    m = Memory(max_turns=3)
    for i in range(5):
        m.add_turn(turn(i))
    users = [x.content for x in m.history() if x.role == "user"]
    assert users == ["q2", "q3", "q4"]


def test_old_tool_output_is_truncated_but_answers_kept():
    m = Memory(max_turns=6, full_turns=1, preview_chars=50)
    m.add_turn(turn(0))
    m.add_turn(turn(1))
    h = m.history()
    tools = [x for x in h if x.role == "tool"]
    assert len(tools[0].content) < 150 and "truncated" in tools[0].content  # old turn
    assert len(tools[1].content) == 1000  # newest turn untouched
    assert [x.content for x in h if x.role == "assistant" and x.content] == ["a0", "a1"]


def test_dangling_tool_call_gets_a_result():
    c = ToolCall("c1", "get_issue", '{"number": 1}')
    m = Memory()
    m.add_turn([Message("user", "q"), Message("assistant", "", tool_calls=(c,)), Message("assistant", "stopped")])
    h = m.history()
    assert h[2].role == "tool" and h[2].tool_call_id == "c1" and "not_executed" in h[2].content


def test_agent_turn_messages_feed_memory(make_agent):
    agent = make_agent([tool_reply(call("echo", {"text": "a"})), text_reply("one"), text_reply("two")])
    mem = Memory()
    r1 = agent.run("first")
    mem.add_turn(r1.turn_messages)
    assert [m.role for m in r1.turn_messages] == ["user", "assistant", "tool", "assistant"]
    r2 = agent.run("second", history=mem.history())
    sent = agent.model.calls[-1]
    assert [m.content for m in sent if m.role == "user"] == ["first", "second"]
    assert r2.answer == "two"


def test_dotenv_does_not_override_env_and_strips_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MAX_STEPS=7   # comment\nGITHUB_REPO=a/b\nMODEL_NAME='m1'\n# x=y\n")
    monkeypatch.setenv("GITHUB_REPO", "from/env")
    for k in ("MAX_STEPS", "MODEL_NAME", "WRITE_REPO_ALLOWLIST"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(env)
    assert s.max_steps == 7 and s.model_name == "m1" and s.github_repo == "from/env"
    assert s.write_allowlist == frozenset({"from/env"})  # defaults to the configured repo
    os.environ.pop("MAX_STEPS"), os.environ.pop("MODEL_NAME")


def test_load_dotenv_missing_file_is_fine(tmp_path):
    load_dotenv(tmp_path / "nope")
