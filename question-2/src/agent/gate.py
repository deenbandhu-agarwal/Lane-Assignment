"""Approval gate for write tools. Lives entirely in code, outside the model's control.

- Approval comes only from an Approver (a human at the terminal, or a fake in tests).
  Nothing the model says, and nothing inside notes or tool output, reaches it.
- Each approval is a one-time token bound to a hash of (tool name, validated args).
  Approving comment A cannot post comment B, and a token cannot be reused.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


def args_digest(tool: str, args: dict[str, Any]) -> str:
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    args: dict[str, Any]
    digest: str


class Approver(Protocol):
    def __call__(self, request: ApprovalRequest) -> bool: ...


class ApprovalGate:
    def __init__(self, approver: Approver) -> None:
        self._approver = approver
        self._issued: dict[str, str] = {}  # token -> digest; removed on use

    def request(self, tool: str, args: dict[str, Any]) -> str | None:
        """Ask the approver. Returns a one-time token if approved, else None."""
        req = ApprovalRequest(tool, args, args_digest(tool, args))
        if not self._approver(req):
            return None
        token = secrets.token_hex(16)
        self._issued[token] = req.digest
        return token

    def consume(self, token: str | None, tool: str, args: dict[str, Any]) -> bool:
        """True only for an unused token issued for exactly this tool + args. Burns the token."""
        if token is None or token not in self._issued:
            return False
        digest = self._issued.pop(token)  # single use, even when the args do not match
        return secrets.compare_digest(digest, args_digest(tool, args))


# -- approvers ---------------------------------------------------------------------


class DenyAll:
    def __call__(self, request: ApprovalRequest) -> bool:
        return False


@dataclass
class ScriptedApprover:
    """Test approver: answers from a fixed list and records what it was asked."""

    answers: Iterable[bool]
    asked: list[ApprovalRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._it = iter(self.answers)

    def __call__(self, request: ApprovalRequest) -> bool:
        self.asked.append(request)
        return next(self._it, False)


class TerminalApprover:
    """Shows the exact write and waits for y/N on the real terminal."""

    def __init__(self, prompt: Callable[[str], str] = input, out: Callable[[str], None] = print):
        self._prompt = prompt
        self._out = out

    def __call__(self, request: ApprovalRequest) -> bool:
        self._out("\n=== WRITE REQUESTED ===")
        self._out(f"tool: {request.tool}")
        for k, v in request.args.items():
            self._out(f"{k}: {v}")
        self._out(f"digest: {request.digest[:16]}")
        try:
            answer = self._prompt("Approve? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}
