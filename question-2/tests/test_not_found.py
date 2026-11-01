"""Required test 5: with no evidence the agent says it couldn't find it and invents nothing.

Two layers are tested:
- retrieval returns no_relevant_results for a question the corpus cannot answer;
- the citation check replaces an answer that cites sources no tool returned
  (a fabricating model), so invented citations never reach the user.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.citations import NOT_FOUND, check_answer, cited_ids
from agent.loop import Agent, StopReason
from agent.models.fake import FakeModelClient, call, text_reply, tool_reply
from agent.models.pricing import price_for
from agent.retrieval.chunker import load_corpus
from agent.retrieval.embedders import FakeEmbedder
from agent.retrieval.index import Retriever
from agent.tools.notes import notes_tool
from agent.tools.registry import ToolRegistry
from agent.trace import read_trace

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
Q = "What was on the 2023 product roadmap?"


def agent(tmp_path, script):
    reg = ToolRegistry([notes_tool(Retriever(load_corpus(CORPUS), FakeEmbedder()))])
    return Agent(FakeModelClient(script), reg, price=price_for("fake"), trace_dir=tmp_path)


def test_search_reports_no_relevant_results(tmp_path):
    a = agent(tmp_path, [tool_reply(call("search_notes", {"query": Q})), text_reply(NOT_FOUND)])
    r = a.run(Q)
    tool_payload = json.loads(next(e for e in read_trace(r.trace_path) if e["event"] == "tool_call")["result"])
    assert tool_payload["data"] == {"status": "no_relevant_results", "results": []}
    assert r.stop_reason is StopReason.FINAL and r.answer == NOT_FOUND


def test_fabricated_answer_with_no_evidence_is_replaced(tmp_path):
    invented = "The 2023 roadmap focused on crypto payouts [roadmap-2023.md#1]."
    a = agent(tmp_path, [tool_reply(call("search_notes", {"query": Q})), text_reply(invented)])
    r = a.run(Q)
    assert r.answer == NOT_FOUND
    cites = next(e for e in read_trace(r.trace_path) if e["event"] == "citations")
    assert cites["unsupported"] == ["roadmap-2023.md#1"] and cites["replaced"] is True


def test_answer_without_any_tool_call_cannot_cite(tmp_path):
    r = agent(tmp_path, [text_reply("Per policy, 3 approvals are needed [release-policy-2025-06.md#1].")]).run("x")
    assert r.answer == NOT_FOUND


def test_supported_citations_pass_untouched(tmp_path):
    q = "What does E4012 mean?"
    good = "E4012 means the access token expired; refresh it [error-codes.md#2]."
    r = agent(tmp_path, [tool_reply(call("search_notes", {"query": q})), text_reply(good)]).run(q)
    assert r.answer == good


def test_partly_unsupported_answer_gets_a_warning():
    check = check_answer("A [a.md#1]. B [b.md#9].", evidence={"a.md#1"})
    assert not check.replaced
    assert check.answer.endswith("may be wrong: b.md#9)")


def test_citation_parsing():
    text = "See [issue#3, error-codes.md#2] and [PR#7]; not a cite: [link], [x]."
    assert cited_ids(text) == {"issue#3", "error-codes.md#2", "pr#7"}
