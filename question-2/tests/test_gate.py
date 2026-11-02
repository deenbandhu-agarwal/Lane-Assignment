"""Required test 1: the gate blocks a write without approval; approvals are single-use;
an approval for args A is rejected for args B.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.gate import ApprovalGate, ApprovalRequest, DenyAll, ScriptedApprover, TerminalApprover, args_digest
from agent.loop import Agent, StopReason
from agent.models.fake import FakeModelClient, call, text_reply, tool_reply
from agent.models.pricing import price_for
from agent.tools.fake_github import FakeGitHub
from agent.tools.github import AllowlistedGitHub, github_tools
from agent.tools.registry import ToolRegistry
from agent.trace import read_trace

REPO = "owner/ledgerly-api"
A = {"number": 5, "body": "summary A"}
B = {"number": 5, "body": "summary B"}


# -- gate unit ---------------------------------------------------------------------


def test_denied_request_gets_no_token():
    assert ApprovalGate(DenyAll()).request("post_issue_comment", A) is None


def test_token_is_single_use():
    gate = ApprovalGate(ScriptedApprover([True]))
    token = gate.request("post_issue_comment", A)
    assert gate.consume(token, "post_issue_comment", A) is True
    assert gate.consume(token, "post_issue_comment", A) is False


def test_approval_for_a_is_rejected_for_b():
    gate = ApprovalGate(ScriptedApprover([True]))
    token = gate.request("post_issue_comment", A)
    assert gate.consume(token, "post_issue_comment", B) is False
    # ...and the mismatch burned it, so it cannot be replayed for A either
    assert gate.consume(token, "post_issue_comment", A) is False


def test_approval_bound_to_tool_name():
    gate = ApprovalGate(ScriptedApprover([True]))
    token = gate.request("post_issue_comment", A)
    assert gate.consume(token, "other_write", A) is False


def test_made_up_token_rejected():
    gate = ApprovalGate(ScriptedApprover([True]))
    gate.request("post_issue_comment", A)
    assert gate.consume("deadbeef" * 4, "post_issue_comment", A) is False
    assert gate.consume(None, "post_issue_comment", A) is False


def test_digest_ignores_key_order_but_not_values():
    assert args_digest("t", {"a": 1, "b": 2}) == args_digest("t", {"b": 2, "a": 1})
    assert args_digest("t", {"a": 1}) != args_digest("t", {"a": 2})


def test_terminal_approver_defaults_to_no():
    lines: list[str] = []
    for answer, expected in [("y", True), ("YES", True), ("", False), ("n", False), ("sure", False)]:
        approver = TerminalApprover(prompt=lambda _p, a=answer: a, out=lines.append)
        assert approver(request_for(A)) is expected
    assert any("summary A" in line for line in lines)  # the human sees the exact text


def test_terminal_approver_eof_is_no():
    def eof(_p):
        raise EOFError

    assert TerminalApprover(prompt=eof, out=lambda _l: None)(request_for(A)) is False


def request_for(args):
    return ApprovalRequest("post_issue_comment", args, args_digest("post_issue_comment", args))


# -- through the agent loop ------------------------------------------------------------


@pytest.fixture
def gh() -> FakeGitHub:
    return FakeGitHub(REPO, issues=[{"number": 5, "title": "Bug triage", "labels": ["bug"]}])


def make(tmp_path: Path, gh: FakeGitHub, script, approver=None, allowlist=frozenset({REPO})):
    client = AllowlistedGitHub(gh, set(allowlist))
    gate = ApprovalGate(approver) if approver is not None else None
    agent = Agent(
        FakeModelClient(script),
        ToolRegistry(github_tools(client), gate=gate),
        price=price_for("fake"),
        trace_dir=tmp_path,
    )
    return agent


def write_then_answer():
    return [tool_reply(call("post_issue_comment", A)), text_reply("done")]


def test_no_gate_means_no_write(tmp_path, gh):
    r = make(tmp_path, gh, write_then_answer(), approver=None).run("post it")
    assert gh.posted == []
    assert '"approval_required"' in r.messages[-2].content


def test_denied_write_does_not_happen(tmp_path, gh):
    approver = ScriptedApprover([False])
    r = make(tmp_path, gh, write_then_answer(), approver).run("post it")
    assert gh.posted == []
    assert len(approver.asked) == 1 and approver.asked[0].args == A
    assert '"approval_denied"' in r.messages[-2].content
    gate_events = [e for e in read_trace(r.trace_path) if e["event"] == "gate"]
    assert [e["decision"] for e in gate_events] == ["denied"]


def test_approved_write_happens_exactly_once(tmp_path, gh):
    approver = ScriptedApprover([True])
    r = make(tmp_path, gh, write_then_answer(), approver).run("post it")
    assert r.stop_reason is StopReason.FINAL
    assert gh.posted == [{"id": 1000, "issue": 5, "body": "summary A"}]


def test_each_write_needs_its_own_approval(tmp_path, gh):
    # Model posts A (approved), then tries B: the earlier approval does not carry over.
    approver = ScriptedApprover([True, False])
    script = [
        tool_reply(call("post_issue_comment", A)),
        tool_reply(call("post_issue_comment", B)),
        text_reply("done"),
    ]
    make(tmp_path, gh, script, approver).run("post twice")
    assert [p["body"] for p in gh.posted] == ["summary A"]
    assert [r.args for r in approver.asked] == [A, B]


def test_model_cannot_self_approve(tmp_path, gh):
    # The model claims approval in text and tries to pass approval-ish args.
    script = [
        tool_reply(call("post_issue_comment", {**A, "approved": True, "token": "x"})),
        tool_reply(call("post_issue_comment", A)),
        text_reply("The user already approved this. APPROVED."),
    ]
    approver = DenyAll()
    make(tmp_path, gh, script, approver).run("post it, I approve in advance")
    assert gh.posted == []


def test_allowlist_refuses_even_after_approval(tmp_path, gh):
    r = make(tmp_path, gh, write_then_answer(), ScriptedApprover([True]), allowlist={"someone/else"}).run("x")
    assert gh.posted == []
    assert '"write_not_allowed"' in r.messages[-2].content


def test_reads_never_ask_for_approval(tmp_path, gh):
    approver = ScriptedApprover([])
    script = [tool_reply(call("list_issues", {"label": "bug"})), text_reply("one bug: #5")]
    make(tmp_path, gh, script, approver).run("bugs?")
    assert approver.asked == []
