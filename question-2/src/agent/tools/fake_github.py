"""In-memory GitHub for offline tests and offline mode. Records every write.

Returns the same shapes as HttpGitHub so answers match between modes.
"""

from __future__ import annotations

import copy
from typing import Any

from agent.tools.github import State
from agent.tools.registry import ToolError


class FakeGitHub:
    def __init__(
        self,
        repo: str = "owner/ledgerly-api",
        issues: list[dict[str, Any]] | None = None,
        pulls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.repo = repo
        self.issues = {i["number"]: copy.deepcopy(i) for i in issues or []}
        self.pulls = {p["number"]: copy.deepcopy(p) for p in pulls or []}
        self.posted: list[dict[str, Any]] = []  # every write that actually happened

    @classmethod
    def from_sandbox(cls, repo: str = "owner/ledgerly-api") -> FakeGitHub:
        from agent.sandbox_data import ISSUES, PULLS

        return cls(repo, ISSUES, PULLS)

    @staticmethod
    def _match(state: State, item: dict[str, Any]) -> bool:
        return state == "all" or item.get("state", "open") == state

    def list_issues(self, state: State, label: str | None) -> list[dict[str, Any]]:
        return [
            {
                "number": i["number"],
                "title": i.get("title", ""),
                "state": i.get("state", "open"),
                "labels": i.get("labels", []),
            }
            for i in self.issues.values()
            if self._match(state, i) and (label is None or label in i.get("labels", []))
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        if number not in self.issues:
            raise ToolError("not_found", f"issue #{number} does not exist", number=number)
        i = self.issues[number]
        return {
            "number": number,
            "title": i.get("title", ""),
            "state": i.get("state", "open"),
            "labels": i.get("labels", []),
            "body": i.get("body", ""),
            "comments": copy.deepcopy(i.get("comments", [])),
        }

    def list_pulls(self, state: State) -> list[dict[str, Any]]:
        return [
            {
                "number": p["number"],
                "title": p.get("title", ""),
                "state": p.get("state", "open"),
                "draft": p.get("draft", False),
                "merged": p.get("merged", False),
                "linked_issue": p.get("linked_issue"),
            }
            for p in self.pulls.values()
            if self._match(state, p)
        ]

    def get_pull(self, number: int) -> dict[str, Any]:
        if number not in self.pulls:
            raise ToolError("not_found", f"pull request #{number} does not exist", number=number)
        p = self.pulls[number]
        return {
            "number": number,
            "title": p.get("title", ""),
            "state": p.get("state", "open"),
            "draft": p.get("draft", False),
            "merged": p.get("merged", False),
            "body": p.get("body", ""),
            "linked_issue": p.get("linked_issue"),
            "reviews": [
                {"reviewer": r.get("reviewer", "ledgerly-dev"), "state": r["state"], "body": r.get("body", "")}
                for r in p.get("reviews", [])
            ],
        }

    def post_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        if number not in self.issues:
            raise ToolError("not_found", f"issue #{number} does not exist", number=number)
        comment = {"id": 1000 + len(self.posted), "issue": number, "body": body}
        self.posted.append(comment)
        self.issues[number].setdefault("comments", []).append({"author": "agent", "body": body})
        return {"comment_id": comment["id"], "issue": number}
