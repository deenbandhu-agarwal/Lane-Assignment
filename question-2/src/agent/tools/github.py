"""GitHub tools: four reads and one gated write (post_issue_comment).

The repo is fixed by configuration, never chosen by the model. The client also
refuses writes to any repo outside WRITE_REPO_ALLOWLIST, even after approval.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent.tools.registry import Tool, ToolError

State = Literal["open", "closed", "all"]


class GitHubClient(Protocol):
    repo: str

    def list_issues(self, state: State, label: str | None) -> list[dict[str, Any]]: ...
    def get_issue(self, number: int) -> dict[str, Any]: ...
    def list_pulls(self, state: State) -> list[dict[str, Any]]: ...
    def get_pull(self, number: int) -> dict[str, Any]: ...
    def post_issue_comment(self, number: int, body: str) -> dict[str, Any]: ...


class AllowlistedGitHub:
    """Wraps any client; refuses writes unless its repo is allowlisted. Independent of the gate."""

    def __init__(self, inner: GitHubClient, allowlist: set[str]) -> None:
        self._inner = inner
        self.repo = inner.repo
        self._allow = {r.strip().lower() for r in allowlist if r.strip()}

    def list_issues(self, state: State, label: str | None) -> list[dict[str, Any]]:
        return self._inner.list_issues(state, label)

    def get_issue(self, number: int) -> dict[str, Any]:
        return self._inner.get_issue(number)

    def list_pulls(self, state: State) -> list[dict[str, Any]]:
        return self._inner.list_pulls(state)

    def get_pull(self, number: int) -> dict[str, Any]:
        return self._inner.get_pull(number)

    def post_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        if self.repo.lower() not in self._allow:
            raise ToolError("write_not_allowed", f"writes to {self.repo} are not allowlisted")
        return self._inner.post_issue_comment(number, body)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListIssuesArgs(_Args):
    state: State = "open"
    label: str | None = Field(None, description="Only issues with this label, e.g. 'bug'")


class NumberArgs(_Args):
    number: int = Field(gt=0, description="Issue or pull request number")


class ListPullsArgs(_Args):
    state: State = "open"


class PostCommentArgs(_Args):
    number: int = Field(gt=0, description="Issue number to comment on")
    body: str = Field(min_length=1, max_length=4000, description="Markdown comment text")


def github_tools(gh: GitHubClient) -> list[Tool]:
    return [
        Tool(
            "list_issues",
            "List issues (not pull requests) in the team repo, optionally filtered by label.",
            ListIssuesArgs,
            lambda a: gh.list_issues(a.state, a.label),
        ),
        Tool(
            "get_issue",
            "Get one issue with its body, labels and comments.",
            NumberArgs,
            lambda a: gh.get_issue(a.number),
        ),
        Tool(
            "list_pulls",
            "List pull requests with the issue each one links to.",
            ListPullsArgs,
            lambda a: gh.list_pulls(a.state),
        ),
        Tool(
            "get_pull",
            "Get one pull request with its description, reviewers and review states.",
            NumberArgs,
            lambda a: gh.get_pull(a.number),
        ),
        Tool(
            "post_issue_comment",
            "Post a comment on an issue. This is a WRITE: a human must approve the exact text "
            "before it runs, and it may be refused.",
            PostCommentArgs,
            lambda a: gh.post_issue_comment(a.number, a.body),
            writes=True,
        ),
    ]
