import asyncio
import hashlib
import hmac

from conftest import CASES, SAMPLE

from reviewpilot import review_diff
from reviewpilot.evaluate import evaluate, load_cases
from reviewpilot.github import build_review_payload, should_review, verify_signature
from reviewpilot.mcp_server import handle
from reviewpilot.sarif import to_sarif
from reviewpilot.store import Store


def test_webhook_signature():
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_signature("s3cret", body, sig)
    assert not verify_signature("s3cret", body + b" ", sig)
    assert not verify_signature("s3cret", body, None) and not verify_signature("", body, sig)


def test_should_review_only_open_non_draft_prs():
    pr = {"state": "open", "draft": False}
    assert should_review("pull_request", {"action": "opened", "pull_request": pr})
    assert should_review("pull_request", {"action": "synchronize", "pull_request": pr})
    assert not should_review("pull_request", {"action": "closed", "pull_request": pr})
    assert not should_review("pull_request", {"action": "opened", "pull_request": {**pr, "draft": True}})
    assert not should_review("push", {})


def test_review_payload_has_inline_comments_on_right_side():
    r = asyncio.run(review_diff(SAMPLE))
    p = build_review_payload(r, "abc123", max_comments=5)
    assert p["event"] == "REQUEST_CHANGES" and p["commit_id"] == "abc123"
    assert len(p["comments"]) == 5 and all(c["side"] == "RIGHT" for c in p["comments"])
    assert "more finding(s) not shown inline" in p["body"]
    assert p["comments"][0]["body"].startswith("🔴")


def test_sarif_is_valid_shape():
    s = to_sarif(asyncio.run(review_diff(SAMPLE)))
    run = s["runs"][0]
    assert s["version"] == "2.1.0" and run["tool"]["driver"]["name"] == "ReviewPilot"
    assert {r["level"] for r in run["results"]} <= {"error", "warning", "note"}
    assert run["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"] > 0


def test_store_roundtrip(tmp_path):
    st = Store(tmp_path / "rp.db")
    r = asyncio.run(review_diff(SAMPLE))
    rid = st.save(r, repo="acme/shop", pr_number=7, title="Add sync")
    assert st.get(rid)["result"]["verdict"] == "request_changes"
    assert st.list()[0]["finding_count"] == len(r.findings)
    stats = st.stats()
    assert stats["reviews"] == 1 and stats["by_category"]["security"] >= 3


def test_mcp_server_protocol():
    init = asyncio.run(handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
    assert init["result"]["serverInfo"]["name"] == "reviewpilot"
    tools = asyncio.run(handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    assert {t["name"] for t in tools["result"]["tools"]} == {"review_diff", "review_working_tree", "list_rules"}
    res = asyncio.run(handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "review_diff", "arguments": {"diff": SAMPLE}}}))
    text = res["result"]["content"][0]["text"]
    assert "app/orders.py:13" in text and res["result"]["isError"] is False
    assert asyncio.run(handle({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None
    bad = asyncio.run(handle({"jsonrpc": "2.0", "id": 4, "method": "nope"}))
    assert bad["error"]["code"] == -32601


def test_benchmark_regression_gate():
    """Fails CI if a rule change lowers precision or recall on the labelled benchmark."""
    rep = asyncio.run(evaluate(load_cases(CASES)))
    assert rep.labels >= 35 and rep.cases >= 15
    assert rep.overall.precision >= 0.95, rep.false_positives
    assert rep.overall.recall >= 0.85, rep.misses
    assert rep.clean_false_positives == 0
