import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi")

from conftest import SAMPLE
from fastapi.testclient import TestClient

from reviewpilot.api import create_app
from reviewpilot.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "whsec")
    return TestClient(create_app(Store(tmp_path / "t.db")))


def test_review_endpoint_and_history(client):
    r = client.post("/api/review", json={"diff": SAMPLE, "repo": "acme/shop"})
    assert r.status_code == 200 and r.json()["verdict"] == "request_changes"
    rid = r.json()["id"]
    assert client.get(f"/api/reviews/{rid}").json()["repo"] == "acme/shop"
    assert client.get("/api/reviews").json()[0]["id"] == rid
    assert client.get("/api/stats").json()["reviews"] == 1
    assert client.get("/api/reviews/999").status_code == 404


def test_webhook_rejects_bad_signature_and_ignores_other_events(client):
    body = json.dumps({"action": "closed"}).encode()
    assert client.post("/webhooks/github", content=body, headers={"X-GitHub-Event": "pull_request",
                       "X-Hub-Signature-256": "sha256=bad"}).status_code == 401
    sig = "sha256=" + hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    r = client.post("/webhooks/github", content=body,
                    headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig})
    assert r.status_code == 202 and r.json() == {"status": "ignored"}


def test_dashboard_and_health(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "ReviewPilot" in client.get("/").text
