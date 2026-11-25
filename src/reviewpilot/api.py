"""FastAPI service: GitHub webhook, review API, and the dashboard."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .github import GitHubClient, build_review_payload, should_review, verify_signature
from .llm import provider_from_env
from .pipeline import review_diff
from .store import Store

log = logging.getLogger("reviewpilot")
DASHBOARD = Path(__file__).resolve().parent / "static" / "index.html"


class ReviewRequest(BaseModel):
    diff: str = Field(min_length=1, max_length=2_000_000)
    repo: str = "playground"
    title: str = ""


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="ReviewPilot", version="0.1.0",
                  description="Multi-agent AI code review for pull requests.")
    app.state.store = store or Store(os.getenv("REVIEWPILOT_DB", "reviewpilot.db"))
    app.state.provider = provider_from_env()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": app.state.provider.name}

    @app.get("/")
    async def dashboard() -> FileResponse:
        return FileResponse(DASHBOARD)

    @app.post("/api/review")
    async def review(req: ReviewRequest) -> dict[str, Any]:
        result = await review_diff(req.diff, app.state.provider)
        rid = app.state.store.save(result, repo=req.repo, title=req.title)
        return {"id": rid, **result.to_dict()}

    @app.get("/api/reviews")
    async def reviews(limit: int = 50, repo: str | None = None) -> list[dict[str, Any]]:
        return app.state.store.list(min(limit, 200), repo)

    @app.get("/api/reviews/{review_id}")
    async def get_review(review_id: int) -> dict[str, Any]:
        r = app.state.store.get(review_id)
        if not r:
            raise HTTPException(404, "review not found")
        return r

    @app.get("/api/stats")
    async def stats() -> dict[str, Any]:
        return app.state.store.stats()

    @app.post("/webhooks/github", status_code=202)
    async def webhook(request: Request, background: BackgroundTasks,
                      x_github_event: str = Header(""), x_hub_signature_256: str | None = Header(None)):
        body = await request.body()
        if not verify_signature(os.getenv("GITHUB_WEBHOOK_SECRET", ""), body, x_hub_signature_256):
            raise HTTPException(401, "bad signature")
        payload = json.loads(body)
        if not should_review(x_github_event, payload):
            return {"status": "ignored"}
        background.add_task(_review_pr, app, payload)
        return {"status": "queued"}

    return app


async def _review_pr(app: FastAPI, payload: dict[str, Any]) -> None:
    pr = payload["pull_request"]
    repo = payload["repository"]["full_name"]
    number, sha = pr["number"], pr["head"]["sha"]
    try:
        gh = await GitHubClient.for_installation(
            os.environ["GITHUB_APP_ID"], _private_key(), payload["installation"]["id"])
        await gh.set_status(repo, sha, "pending", "ReviewPilot agents are reviewing…")
        diff = await gh.get_pr_diff(repo, number)
        result = await review_diff(diff, app.state.provider)
        await gh.post_review(repo, number, build_review_payload(result, sha))
        app.state.store.save(result, repo=repo, pr_number=number, title=pr.get("title", ""), commit_sha=sha)
        crit = sum(1 for f in result.findings if f.severity.value in ("critical", "high"))
        await gh.set_status(repo, sha, "failure" if crit else "success",
                            f"{len(result.findings)} finding(s), {crit} high or critical")
    except Exception:
        log.exception("review failed for %s#%s", repo, number)


def _private_key() -> str:
    if key := os.getenv("GITHUB_PRIVATE_KEY"):
        return key.replace("\\n", "\n")
    return Path(os.environ["GITHUB_PRIVATE_KEY_PATH"]).read_text()


app = create_app() if os.getenv("REVIEWPILOT_EAGER_APP", "1") == "1" else None
