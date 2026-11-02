"""Real GitHub REST client (httpx). Read paths trim responses to what the agent needs;
every HTTP failure becomes a ToolError the model can read."""

from __future__ import annotations

import re
from typing import Any

import httpx

from agent.tools.github import State
from agent.tools.registry import ToolError

_LINK = re.compile(r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)", re.I)


def linked_issue(body: str | None) -> int | None:
    m = _LINK.search(body or "")
    return int(m.group(1)) if m else None


class HttpGitHub:
    def __init__(
        self,
        token: str,
        repo: str,
        *,
        base_url: str = "https://api.github.com",
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN is empty")
        self.repo = repo
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ledgerly-agent",
            },
        )

    # -- http -------------------------------------------------------------------

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._http.request(method, f"/repos/{self.repo}{path}", **kw)
        except httpx.TimeoutException:
            raise ToolError("github_timeout", "GitHub did not answer in time; try again") from None
        except httpx.HTTPError as e:
            raise ToolError("github_unavailable", f"could not reach GitHub: {type(e).__name__}") from None
        if r.status_code == 404:
            raise ToolError("not_found", f"{path} does not exist")
        if r.status_code in (401, 403):
            raise ToolError("github_forbidden", f"GitHub refused the request ({r.status_code})")
        if r.status_code == 422:
            raise ToolError("invalid_request", r.json().get("message", "unprocessable"))
        if r.status_code >= 400:
            raise ToolError("github_unavailable", f"GitHub returned {r.status_code}")
        return r.json() if r.content else None

    # -- reads ------------------------------------------------------------------

    def list_issues(self, state: State, label: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"state": state, "per_page": 50}
        if label:
            params["labels"] = label
        items = self._request("GET", "/issues", params=params)
        return [
            {
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "labels": [lab["name"] for lab in i.get("labels", [])],
            }
            for i in items
            if "pull_request" not in i  # the issues endpoint also returns PRs
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        i = self._request("GET", f"/issues/{number}")
        if "pull_request" in i:
            raise ToolError("not_an_issue", f"#{number} is a pull request; use get_pull", number=number)
        comments = self._request("GET", f"/issues/{number}/comments", params={"per_page": 50})
        return {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "labels": [lab["name"] for lab in i.get("labels", [])],
            "body": i.get("body") or "",
            "comments": [{"author": c["user"]["login"], "body": c.get("body") or ""} for c in comments],
        }

    def list_pulls(self, state: State) -> list[dict[str, Any]]:
        items = self._request("GET", "/pulls", params={"state": state, "per_page": 50})
        return [
            {
                "number": p["number"],
                "title": p["title"],
                "state": p["state"],
                "draft": p.get("draft", False),
                "merged": bool(p.get("merged_at")),
                "linked_issue": linked_issue(p.get("body")),
            }
            for p in items
        ]

    def get_pull(self, number: int) -> dict[str, Any]:
        p = self._request("GET", f"/pulls/{number}")
        reviews = self._request("GET", f"/pulls/{number}/reviews", params={"per_page": 50})
        return {
            "number": p["number"],
            "title": p["title"],
            "state": p["state"],
            "draft": p.get("draft", False),
            "merged": bool(p.get("merged_at")),
            "body": p.get("body") or "",
            "linked_issue": linked_issue(p.get("body")),
            "reviews": [
                {"reviewer": r["user"]["login"], "state": r["state"], "body": r.get("body") or ""}
                for r in reviews
            ],
        }

    # -- eval cleanup only (not exposed as a tool) ----------------------------------

    def delete_issue_comment(self, comment_id: int) -> None:
        self._request("DELETE", f"/issues/comments/{comment_id}")

    # -- the one write ------------------------------------------------------------

    def post_issue_comment(self, number: int, body: str) -> dict[str, Any]:
        c = self._request("POST", f"/issues/{number}/comments", json={"body": body})
        return {"comment_id": c["id"], "issue": number, "url": c.get("html_url")}
