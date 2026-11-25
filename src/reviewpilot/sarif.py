"""SARIF 2.1.0 output, so findings show up in GitHub's Security → Code scanning tab."""

from __future__ import annotations

from typing import Any

from . import __version__
from .models import ReviewResult, Severity

LEVEL = {Severity.CRITICAL: "error", Severity.HIGH: "error", Severity.MEDIUM: "warning", Severity.LOW: "note"}
SCORE = {Severity.CRITICAL: "9.5", Severity.HIGH: "7.5", Severity.MEDIUM: "5.0", Severity.LOW: "2.0"}


def to_sarif(result: ReviewResult) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    results = []
    for f in result.findings:
        rid = f.rule_id or f"{f.category.value}"
        rules.setdefault(rid, {
            "id": rid, "name": f.title.replace(" ", ""), "shortDescription": {"text": f.title},
            "properties": {"tags": [f.category.value], "security-severity": SCORE[f.severity]},
        })
        msg = f.message + (f"\n\nSuggested fix: {f.suggestion}" if f.suggestion else "")
        results.append({
            "ruleId": rid, "level": LEVEL[f.severity], "message": {"text": msg},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.file},
                                                "region": {"startLine": f.line}}}],
            "properties": {"confidence": f.confidence, "source": f.source},
        })
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{"tool": {"driver": {"name": "ReviewPilot", "version": __version__,
                                      "informationUri": "https://github.com/kdurgareddy/reviewpilot",
                                      "rules": list(rules.values())}},
                  "results": results}],
    }
