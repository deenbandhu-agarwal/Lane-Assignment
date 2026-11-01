"""Typed tool registry: args validated before execution, structured recoverable errors."""

from __future__ import annotations

import json

from pydantic import BaseModel

from agent.models.fake import call
from agent.tools.registry import Tool, ToolError, ToolRegistry


def err(result) -> dict:
    body = json.loads(result.content)
    assert body["ok"] is False
    return body["error"]


def test_valid_call_runs(registry):
    r = registry.execute(call("echo", {"text": "hi"}))
    assert r.ok and json.loads(r.content) == {"ok": True, "data": {"echo": "hi"}}


def test_unknown_tool_lists_available(registry):
    e = err(registry.execute(call("nope", {})))
    assert e["type"] == "unknown_tool" and e["available"] == ["echo"]


def test_invalid_json(registry):
    assert err(registry.execute(call("echo", "{bad")))["type"] == "invalid_json"


def test_non_object_args(registry):
    assert err(registry.execute(call("echo", "[1, 2]")))["type"] == "invalid_args"


def test_schema_violation_names_the_field(registry):
    e = err(registry.execute(call("echo", {"text": "x", "times": "many"})))
    assert e["type"] == "invalid_args"
    assert any(p["field"] == "times" for p in e["problems"])


def test_extra_args_rejected(registry):
    e = err(registry.execute(call("echo", {"text": "x", "rm": "-rf"})))
    assert any(p["field"] == "rm" for p in e["problems"])


def test_tool_does_not_run_when_args_invalid():
    ran = []

    class A(BaseModel):
        n: int

    reg = ToolRegistry([Tool("t", "", A, lambda a: ran.append(a))])
    reg.execute(call("t", {"n": "x"}))
    assert ran == []


def test_tool_errors_are_structured_not_raised():
    class A(BaseModel):
        pass

    def not_found(_):
        raise ToolError("not_found", "issue 99 does not exist", number=99)

    def buggy(_):
        raise KeyError("boom")

    reg = ToolRegistry([Tool("nf", "", A, not_found), Tool("bug", "", A, buggy)])
    assert err(reg.execute(call("nf"))) == {
        "type": "not_found",
        "message": "issue 99 does not exist",
        "number": 99,
    }
    assert err(reg.execute(call("bug")))["type"] == "tool_failed"


def test_specs_expose_json_schema(registry):
    (spec,) = registry.specs()
    assert spec.name == "echo"
    assert spec.parameters["required"] == ["text"]
