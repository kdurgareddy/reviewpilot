"""GitHub integration: webhook verification, GitHub App auth, and posting reviews.

Two ways to authenticate:

* **GitHub App** (recommended): sign a short-lived JWT with the app's private key,
  exchange it for an installation token, and act as ``reviewpilot[bot]``.
* **Token** (GitHub Actions): use the workflow's ``GITHUB_TOKEN``.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any

from .models import Finding, ReviewResult
from .summary import render_comment

API = "https://api.github.com"
EVENT_FOR_VERDICT = {"approve": "COMMENT", "comment": "COMMENT", "request_changes": "REQUEST_CHANGES"}


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Check ``X-Hub-Signature-256`` in constant time."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def should_review(event: str, payload: dict[str, Any]) -> bool:
    if event != "pull_request":
        return False
    pr = payload.get("pull_request") or {}
    return (
        payload.get("action") in {"opened", "synchronize", "reopened", "ready_for_review"}
        and not pr.get("draft", False)
        and pr.get("state") == "open"
    )


def app_jwt(app_id: str, private_key_pem: str, now: int | None = None) -> str:
    """JWT for authenticating as the GitHub App (valid 9 minutes, back-dated 60 s for clock skew)."""
    import jwt  # PyJWT[crypto]

    now = int(now or time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key_pem, algorithm="RS256")


def build_review_payload(result: ReviewResult, commit_sha: str, max_comments: int = 30) -> dict[str, Any]:
    """Body for POST /repos/{owner}/{repo}/pulls/{n}/reviews with inline comments on the RIGHT side."""
    comments = [_inline(f) for f in result.findings[:max_comments]]
    body = result.summary
    extra = len(result.findings) - len(comments)
    if extra > 0:
        body += f"\n\n_{extra} more finding(s) not shown inline._"
    return {
        "commit_id": commit_sha,
        "event": EVENT_FOR_VERDICT[result.verdict],
        "body": body,
        "comments": comments,
    }


def _inline(f: Finding) -> dict[str, Any]:
    return {"path": f.file, "line": f.line, "side": "RIGHT", "body": render_comment(f)}


@dataclass
class GitHubClient:
    token: str
    base_url: str = API

    def _client(self):
        import httpx

        return httpx.AsyncClient(
            base_url=self.base_url, timeout=30,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "reviewpilot"},
        )

    @classmethod
    async def for_installation(cls, app_id: str, private_key: str, installation_id: int) -> "GitHubClient":
        import httpx

        async with httpx.AsyncClient(base_url=API, timeout=30) as c:
            r = await c.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {app_jwt(app_id, private_key)}",
                         "Accept": "application/vnd.github+json"},
            )
            r.raise_for_status()
            return cls(r.json()["token"])

    async def get_pr_diff(self, repo: str, number: int) -> str:
        async with self._client() as c:
            r = await c.get(f"/repos/{repo}/pulls/{number}", headers={"Accept": "application/vnd.github.v3.diff"})
            r.raise_for_status()
            return r.text

    async def post_review(self, repo: str, number: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.post(f"/repos/{repo}/pulls/{number}/reviews", json=payload)
            if r.status_code == 422 and payload.get("comments"):
                # A comment pointed at a line GitHub won't accept (e.g. outside the diff):
                # fall back to a summary-only review instead of failing.
                fallback = {**payload, "comments": [],
                            "body": payload["body"] + "\n\n_Inline comments could not be attached; see details above._"}
                r = await c.post(f"/repos/{repo}/pulls/{number}/reviews", json=fallback)
            r.raise_for_status()
            return r.json()

    async def set_status(self, repo: str, sha: str, state: str, description: str) -> None:
        async with self._client() as c:
            await c.post(f"/repos/{repo}/statuses/{sha}",
                         json={"state": state, "context": "reviewpilot", "description": description[:140]})
