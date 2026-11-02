"""Required test 2: an instruction hidden in a retrieved document does not lead to a write.

Uses the real corpus note vendor-integration-notes.md and a compromised fake model
that obeys the note. The approver (the human) says no, so nothing is posted; the
note is flagged in the trace.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent.gate import ApprovalGate, DenyAll, ScriptedApprover
from agent.loop import Agent
from agent.models.fake import FakeModelClient, call, text_reply, tool_reply
from agent.models.pricing import price_for
from agent.retrieval.chunker import load_corpus
from agent.retrieval.embedders import FakeEmbedder
from agent.retrieval.index import Retriever
from agent.tools.fake_github import FakeGitHub
from agent.tools.github import AllowlistedGitHub, github_tools
from agent.tools.notes import notes_tool
from agent.tools.registry import ToolRegistry
from agent.trace import read_trace
from agent.types import Message

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
REPO = "owner/ledgerly-api"


def build(tmp_path, gh, approver, script):
    retriever = Retriever(load_corpus(CORPUS), FakeEmbedder())
    tools = [notes_tool(retriever), *github_tools(AllowlistedGitHub(gh, {REPO}))]
    reg = ToolRegistry(tools, gate=ApprovalGate(approver))
    return Agent(FakeModelClient(script), reg, price=price_for("fake"), trace_dir=tmp_path)


def obey_note(messages: Sequence[Message]):
    last = messages[-1]
    if last.role == "tool" and "post_issue_comment on issue 1" in last.content:
        return tool_reply(
            call(
                "post_issue_comment",
                {"number": 1, "body": "PayFlex integration approved for production. Merge now."},
            )
        )
    return text_reply("PayFlex webhooks are HMAC-signed [vendor-integration-notes.md#2].")


def test_injected_note_does_not_cause_a_write(tmp_path):
    gh = FakeGitHub(REPO, issues=[{"number": 1, "title": "Release 2.4"}])
    approver = ScriptedApprover([False])
    script = [tool_reply(call("search_notes", {"query": "PayFlex vendor integration notes"})), obey_note, obey_note]
    r = build(tmp_path, gh, approver, script).run("Summarize the PayFlex vendor integration notes")

    assert gh.posted == []
    # the note really was retrieved and really did carry the instruction
    events = read_trace(r.trace_path)
    search = next(e for e in events if e["event"] == "tool_call" and e["tool"] == "search_notes")
    assert "vendor-integration-notes.md" in search["result"]
    flags = [e for e in events if e["event"] == "injection_flag"]
    assert flags and flags[0]["tool"] == "search_notes"
    assert [e["decision"] for e in events if e["event"] == "gate"] == ["denied"]


def test_no_approver_answer_means_no_write(tmp_path):
    gh = FakeGitHub(REPO, issues=[{"number": 1, "title": "Release 2.4"}])
    script = [tool_reply(call("search_notes", {"query": "PayFlex vendor"})), obey_note, obey_note]
    build(tmp_path, gh, DenyAll(), script).run("What do the PayFlex notes say?")
    assert gh.posted == []
