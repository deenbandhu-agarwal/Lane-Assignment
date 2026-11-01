"""Fill the private sandbox repo with the fixed issues, PRs, comments and reviews.

    uv run python scripts/seed_sandbox.py            # dry run: prints the plan
    uv run python scripts/seed_sandbox.py --apply    # does it

Needs a token with Issues, Pull requests and Contents write on GITHUB_REPO
(GITHUB_SEED_TOKEN if set, else GITHUB_TOKEN). Safe to re-run: items that already
exist with the expected number and title are skipped. Refuses if the repo holds
anything else, because the eval relies on exact numbers (1-11).
"""

from __future__ import annotations

import argparse
import base64
import os
import sys

import httpx

from agent.config import Settings
from agent.sandbox_data import ISSUES, LABELS, PULLS


class GH:
    def __init__(self, token: str, repo: str) -> None:
        self.repo = repo
        self.http = httpx.Client(
            base_url=f"https://api.github.com/repos/{repo}",
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def call(self, method: str, path: str, ok: tuple[int, ...] = (200, 201), **kw):
        r = self.http.request(method, path, **kw)
        if r.status_code not in ok:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    s = Settings.from_env()
    token = os.environ.get("GITHUB_SEED_TOKEN") or s.github_token
    gh = GH(token, s.github_repo)

    expected = {i["number"]: i["title"] for i in ISSUES + PULLS}
    existing = {
        i["number"]: i["title"] for i in gh.call("GET", "/issues", params={"state": "all", "per_page": 100})
    }
    stray = {n: t for n, t in existing.items() if expected.get(n) != t}
    if stray:
        sys.exit(f"{s.github_repo} has unexpected issues/PRs {stray}; seeding needs a clean repo.")
    todo = [n for n in expected if n not in existing]
    print(f"Seeding {s.github_repo}: {len(existing)} of {len(expected)} items exist; to create: {todo}")
    if not args.apply:
        print("dry run; pass --apply to create them")
        return

    for name, color in LABELS.items():
        gh.call("POST", "/labels", ok=(201, 422), json={"name": name, "color": color})

    for issue in ISSUES:
        if issue["number"] in existing:
            continue
        created = gh.call(
            "POST", "/issues", json={"title": issue["title"], "body": issue["body"], "labels": issue["labels"]}
        )
        assert created["number"] == issue["number"], (created["number"], issue["number"])
        for c in issue["comments"]:
            gh.call("POST", f"/issues/{issue['number']}/comments", json={"body": c["body"]})
        print(f"  issue #{issue['number']}: {issue['title']}")

    main_sha = gh.call("GET", "/git/ref/heads/main")["object"]["sha"]
    for pr in PULLS:
        if pr["number"] in existing:
            continue
        gh.call("POST", "/git/refs", ok=(201, 422), json={"ref": f"refs/heads/{pr['branch']}", "sha": main_sha})
        slug = pr["branch"].split("/")[-1]
        gh.call(
            "PUT",
            f"/contents/changes/{slug}.md",
            ok=(201, 422),
            json={
                "message": pr["title"],
                "branch": pr["branch"],
                "content": base64.b64encode(f"# {pr['title']}\n\n{pr['body']}\n".encode()).decode(),
            },
        )
        created = gh.call(
            "POST",
            "/pulls",
            json={"title": pr["title"], "head": pr["branch"], "base": "main", "body": pr["body"], "draft": pr["draft"]},
        )
        assert created["number"] == pr["number"], (created["number"], pr["number"])
        for review in pr["reviews"]:
            gh.call("POST", f"/pulls/{pr['number']}/reviews", json={"event": "COMMENT", "body": review["body"]})
        if pr["merged"]:
            gh.call("PUT", f"/pulls/{pr['number']}/merge", json={"merge_method": "squash"})
        print(f"  PR #{pr['number']}: {pr['title']}")

    for issue in ISSUES:
        if issue["state"] == "closed":
            gh.call("PATCH", f"/issues/{issue['number']}", json={"state": "closed"})
    print("done")


if __name__ == "__main__":
    main()
