"""Real GitHub client against an in-process mock transport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.tools.fake_github import FakeGitHub
from agent.tools.http_github import HttpGitHub, linked_issue
from agent.tools.registry import ToolError

REPO = "owner/ledgerly-api"


def gh(routes: dict[tuple[str, str], tuple[int, object]], seen: list | None = None) -> HttpGitHub:
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        key = (req.method, req.url.path.removeprefix(f"/repos/{REPO}"))
        if key not in routes:
            return httpx.Response(404, json={"message": "Not Found"})
        status, body = routes[key]
        return httpx.Response(status, json=body)

    return HttpGitHub("tok", REPO, transport=httpx.MockTransport(handler))


def test_list_issues_drops_pull_requests_and_passes_filters():
    seen: list[httpx.Request] = []
    items = [
        {"number": 3, "title": "E4012", "state": "open", "labels": [{"name": "bug"}]},
        {"number": 9, "title": "PR", "state": "open", "labels": [], "pull_request": {}},
    ]
    out = gh({("GET", "/issues"): (200, items)}, seen).list_issues("open", "bug")
    assert out == [{"number": 3, "title": "E4012", "state": "open", "labels": ["bug"]}]
    assert seen[0].url.params["labels"] == "bug" and seen[0].headers["authorization"] == "Bearer tok"


def test_get_issue_includes_comments():
    routes = {
        ("GET", "/issues/3"): (200, {"number": 3, "title": "t", "state": "open", "labels": [], "body": "b"}),
        ("GET", "/issues/3/comments"): (200, [{"user": {"login": "u"}, "body": "c"}]),
    }
    assert gh(routes).get_issue(3)["comments"] == [{"author": "u", "body": "c"}]


def test_get_issue_on_a_pr_number_says_so():
    routes = {("GET", "/issues/9"): (200, {"number": 9, "title": "t", "state": "open", "pull_request": {}})}
    with pytest.raises(ToolError) as e:
        gh(routes).get_issue(9)
    assert e.value.type == "not_an_issue"


def test_get_pull_with_reviews_and_link():
    routes = {
        ("GET", "/pulls/9"): (200, {"number": 9, "title": "t", "state": "open", "draft": False, "merged_at": None, "body": "Fixes #3."}),
        ("GET", "/pulls/9/reviews"): (200, [{"user": {"login": "r"}, "state": "COMMENTED", "body": "add a test"}]),
    }
    p = gh(routes).get_pull(9)
    assert p["linked_issue"] == 3 and p["merged"] is False
    assert p["reviews"] == [{"reviewer": "r", "state": "COMMENTED", "body": "add a test"}]


def test_post_comment_sends_body():
    seen: list[httpx.Request] = []
    routes = {("POST", "/issues/5/comments"): (201, {"id": 77, "html_url": "u"})}
    assert gh(routes, seen).post_issue_comment(5, "hello") == {"comment_id": 77, "issue": 5, "url": "u"}
    assert json.loads(seen[0].content) == {"body": "hello"}


@pytest.mark.parametrize("status, kind", [(404, "not_found"), (403, "github_forbidden"), (502, "github_unavailable")])
def test_http_errors_become_tool_errors(status, kind):
    with pytest.raises(ToolError) as e:
        gh({("GET", "/issues/1"): (status, {"message": "x"})}).get_issue(1)
    assert e.value.type == kind


@pytest.mark.parametrize(
    "body, n", [("Fixes #3.", 3), ("closes #12", 12), ("Resolved #4", 4), ("see #5", None), (None, None)]
)
def test_linked_issue(body, n):
    assert linked_issue(body) == n


def test_fake_and_http_return_the_same_shape():
    """Offline mode must look like real mode to the model."""
    fake = FakeGitHub.from_sandbox(REPO)
    assert set(fake.list_issues("all", None)[0]) == {"number", "title", "state", "labels"}
    assert set(fake.get_issue(3)) == {"number", "title", "state", "labels", "body", "comments"}
    assert set(fake.list_pulls("all")[0]) == {"number", "title", "state", "draft", "merged", "linked_issue"}
    assert set(fake.get_pull(9)) == {"number", "title", "state", "draft", "merged", "body", "linked_issue", "reviews"}
