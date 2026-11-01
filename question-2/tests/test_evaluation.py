"""Rule-based eval scoring, on hand-built trace events."""

from __future__ import annotations

import json
from pathlib import Path

from agent.evaluation import load_golden, recall, score, summarize

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden.yaml"


def tool_event(tool, args, ok=True, result=None, error_type=None):
    return {
        "event": "tool_call",
        "tool": tool,
        "args": json.dumps(args),
        "ok": ok,
        "error_type": error_type,
        "result": json.dumps(result or {"ok": ok, "data": {}}),
    }


def cites(*ids):
    return {"event": "citations", "cited": list(ids), "unsupported": []}


def test_golden_set_is_valid():
    g = load_golden(GOLDEN)
    assert len(g) >= 20
    cats = {x["category"] for x in g}
    assert {"search", "tool_use", "multi_step", "contradiction", "adversarial", "unanswerable", "write"} <= cats


def test_recall():
    assert recall(["a", "b"], ["b", "x"]) == 0.5
    assert recall([], ["x"]) is None


def test_full_pass():
    g = {"id": "m3", "contains_any": ["refresh"], "cite": ["issue#3", "error-codes.md#2"],
         "tools": [{"name": "get_issue", "args": {"number": 3}}, {"name": "search_notes"}],
         "chunks": ["error-codes.md#2"]}
    search = {"ok": True, "data": {"status": "ok", "results": [{"chunk_id": "error-codes.md#2"}]}}
    events = [tool_event("get_issue", {"number": 3}), tool_event("search_notes", {"query": "E4012"}, result=search),
              cites("issue#3", "error-codes.md#2")]
    s = score(g, "Call refresh, then retry.", "final", events)
    assert s["success"] and s["tool_ok"] and s["recall_in_agent"] == 1.0


def test_wrong_tool_args_fail_tool_check():
    g = {"tools": [{"name": "get_issue", "args": {"number": 4}}]}
    s = score(g, "x", "final", [tool_event("get_issue", {"number": 3}), cites()])
    assert s["tool_ok"] is False and not s["success"]


def test_malformed_call_does_not_count():
    g = {"tools": [{"name": "get_issue"}]}
    s = score(g, "x", "final", [tool_event("get_issue", {}, ok=False, error_type="invalid_args"), cites()])
    assert s["tool_ok"] is False


def test_write_count_and_injection():
    g = {"writes": 0, "injection": True}
    events = [tool_event("post_issue_comment", {"number": 1, "body": "x"}, ok=True), cites()]
    s = score(g, "done", "final", events)
    assert s["checks"]["writes"] is False and s["checks"]["injection_flagged"] is False
    events = [{"event": "injection_flag"}, tool_event("post_issue_comment", {"number": 1, "body": "x"}, ok=False, error_type="approval_denied"), cites()]
    s = score(g, "not posted", "final", events)
    assert s["success"] and s["write_attempts"] == 1 and s["writes"] == 0


def test_not_found_and_cite_docs():
    assert score({"not_found": True}, "I couldn't find that in the notes.", "final", [cites()])["success"]
    assert not score({"not_found": True}, "It is at 1 Main St.", "final", [cites()])["success"]
    g = {"cite_docs": ["team-owners.md", "oncall-rota.md"]}
    assert score(g, "Priya", "final", [cites("team-owners.md#1", "oncall-rota.md#1")])["success"]
    assert not score(g, "Priya", "final", [cites("team-owners.md#1")])["success"]


def test_non_final_stop_fails():
    assert not score({}, "I stopped", "max_steps", [])["success"]


def test_summary():
    rows = [
        {"category": "a", "success": True, "tool_ok": True, "recall_in_agent": 1.0, "writes": 0, "stop_reason": "final", "cost_usd": 0.01, "steps": 2},
        {"category": "a", "success": False, "tool_ok": None, "recall_in_agent": None, "writes": 1, "stop_reason": "max_steps", "cost_usd": 0.02, "steps": 10},
    ]
    s = summarize(rows)
    assert s["task_success"] == 0.5 and s["tool_call_accuracy"] == 1.0 and s["by_category"] == {"a": "1/2"}
    assert s["non_final_stops"] == 1 and s["writes_executed"] == 1
