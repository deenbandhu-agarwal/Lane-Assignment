"""Typed tool registry.

Args are validated against the tool's pydantic model (its JSON schema is what the
model sees) *before* anything runs. Every failure comes back as a structured error
the model can read and recover from; nothing raises into the loop.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from agent.gate import ApprovalGate
from agent.types import ToolCall, ToolSpec

Audit = Callable[..., None]  # (event_kind, **data), usually Tracer.event

# Error types that mean "the model produced a bad call" (counted towards the malformed limit).
MALFORMED = frozenset({"unknown_tool", "invalid_json", "invalid_args"})


class ToolError(Exception):
    """Raised by a tool for an expected failure (not found, permission, ...)."""

    def __init__(self, type: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.type = type
        self.message = message
        self.details = details


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    fn: Callable[[Any], Any]  # receives the validated args model
    writes: bool = False  # True -> must pass the approval gate

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.args.model_json_schema())


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str  # JSON text sent back to the model
    error_type: str | None = None
    data: Any = field(default=None, compare=False)

    @classmethod
    def success(cls, data: Any) -> ToolResult:
        return cls(ok=True, content=json.dumps({"ok": True, "data": data}, default=str), data=data)

    @classmethod
    def failure(cls, type: str, message: str, **details: Any) -> ToolResult:
        body = {"ok": False, "error": {"type": type, "message": message, **details}}
        return cls(ok=False, content=json.dumps(body, default=str), error_type=type)

    @property
    def malformed(self) -> bool:
        return self.error_type in MALFORMED


class ToolRegistry:
    """Write tools only ever run through the approval gate; without a gate they are refused."""

    def __init__(self, tools: Iterable[Tool] = (), *, gate: ApprovalGate | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._gate = gate
        for t in tools:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def write_tool_names(self) -> frozenset[str]:
        return frozenset(n for n, t in self._tools.items() if t.writes)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def parse(self, call: ToolCall) -> tuple[Tool, BaseModel] | ToolResult:
        """Resolve + validate a call. Returns (tool, args) or a failure result."""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult.failure(
                "unknown_tool", f"no tool named {call.name!r}", available=sorted(self._tools)
            )
        try:
            raw = json.loads(call.raw_args or "{}")
        except json.JSONDecodeError as e:
            return ToolResult.failure("invalid_json", f"arguments are not valid JSON: {e.msg}")
        if not isinstance(raw, dict):
            return ToolResult.failure("invalid_args", "arguments must be a JSON object")
        try:
            args = tool.args.model_validate(raw)
        except ValidationError as e:
            problems = [
                {"field": ".".join(str(p) for p in err["loc"]) or "(root)", "problem": err["msg"]}
                for err in e.errors()
            ]
            return ToolResult.failure("invalid_args", "arguments failed validation", problems=problems)
        return tool, args

    def execute(self, call: ToolCall, audit: Audit | None = None) -> ToolResult:
        parsed = self.parse(call)
        if isinstance(parsed, ToolResult):
            return parsed
        tool, args = parsed
        if tool.writes:
            return self._gated(tool, args, audit or (lambda *_a, **_k: None))
        return self.invoke(tool, args)

    def _gated(self, tool: Tool, args: BaseModel, audit: Audit) -> ToolResult:
        if self._gate is None:
            audit("gate", tool=tool.name, decision="no_gate")
            return ToolResult.failure("approval_required", "write tools are disabled in this session")
        plain = args.model_dump(mode="json")
        token = self._gate.request(tool.name, plain)
        if token is None:
            audit("gate", tool=tool.name, args=plain, decision="denied")
            return ToolResult.failure(
                "approval_denied", "the human did not approve this write; it was not performed"
            )
        if not self._gate.consume(token, tool.name, plain):
            audit("gate", tool=tool.name, args=plain, decision="token_rejected")
            return ToolResult.failure("approval_invalid", "approval did not match this write")
        audit("gate", tool=tool.name, args=plain, decision="approved")
        return self.invoke(tool, args)

    @staticmethod
    def invoke(tool: Tool, args: BaseModel) -> ToolResult:
        try:
            return ToolResult.success(tool.fn(args))
        except ToolError as e:
            return ToolResult.failure(e.type, e.message, **e.details)
        except Exception as e:  # a buggy tool must not crash the run
            return ToolResult.failure("tool_failed", f"{type(e).__name__}: {e}")
