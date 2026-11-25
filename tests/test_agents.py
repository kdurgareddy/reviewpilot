import asyncio

from conftest import new_file_diff

from reviewpilot import review_diff
from reviewpilot.llm import CachedProvider, ScriptedProvider, parse_json

CODE = """import subprocess


def backup(path):
    subprocess.run(f"tar czf b.tgz {path}", shell=True)


def page(items, n):
    return items[n * 10:n * 10 + 9]
"""
DIFF = new_file_diff("app/tools.py", CODE)


def test_llm_confirms_hint_and_adds_logic_bug():
    llm = ScriptedProvider({
        "security": {"findings": [{"line": 5, "severity": "high", "title": "Command injection",
                                   "message": "path is interpolated into a shell command.",
                                   "confidence": 0.95, "confirms_rule": "SEC007"}]},
        "bugs": {"findings": [{"line": 9, "severity": "medium", "title": "Off-by-one page size",
                               "message": "Slice returns 9 items, not 10.", "confidence": 0.85}]},
    })
    r = asyncio.run(review_diff(DIFF, llm))
    by_line = {f.line: f for f in r.findings}
    assert by_line[5].source == "static+llm" and by_line[5].message.startswith("path is interpolated")
    assert by_line[5].confidence > 0.9
    assert by_line[9].source == "llm" and by_line[9].category.value == "bug"
    assert r.usage.calls >= 2 and r.model == "scripted"


def test_llm_rejected_hint_is_dropped():
    llm = ScriptedProvider({"security": {"findings": [], "rejected_hints": ["SEC007@app/tools.py:5"]}})
    r = asyncio.run(review_diff(DIFF, llm))
    assert not [f for f in r.findings if f.rule_id == "SEC007"]
    assert r.dropped >= 1


def test_hallucinated_line_is_removed_by_verifier():
    llm = ScriptedProvider({"bugs": {"findings": [{"line": 400, "severity": "high", "title": "Ghost",
                                                    "message": "Not a real line.", "confidence": 0.9}]}})
    r = asyncio.run(review_diff(DIFF, llm))
    assert all(f.line != 400 for f in r.findings)


def test_low_confidence_llm_findings_are_filtered():
    llm = ScriptedProvider({"bugs": {"findings": [{"line": 9, "severity": "low", "title": "Maybe",
                                                    "message": "Unsure.", "confidence": 0.3}]}})
    r = asyncio.run(review_diff(DIFF, llm))
    assert not [f for f in r.findings if f.title == "Maybe"]


def test_outage_falls_back_to_static_rules():
    llm = ScriptedProvider({}, fail_times=100)
    r = asyncio.run(review_diff(DIFF, llm))
    assert any(f.rule_id == "SEC007" for f in r.findings)
    assert "model was unavailable" in r.summary


def test_transient_failure_is_retried():
    llm = ScriptedProvider({"security": {"findings": [{"line": 5, "severity": "high", "title": "Injection",
                                                       "message": "x", "confidence": 0.9, "confirms_rule": "SEC007"}]}},
                           fail_times=1)
    r = asyncio.run(review_diff(DIFF, llm))
    assert "model was unavailable" not in r.summary
    assert any(f.source == "static+llm" for f in r.findings)


def test_cache_avoids_repeat_calls():
    inner = ScriptedProvider({})
    cached = CachedProvider(inner)
    asyncio.run(review_diff(DIFF, cached))
    first = len(inner.calls)
    asyncio.run(review_diff(DIFF, cached))
    assert len(inner.calls) == first and cached.hits == first


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"findings": []}\n```') == {"findings": []}
    assert parse_json('Sure! {"findings": [1]} done') == {"findings": [1]}
