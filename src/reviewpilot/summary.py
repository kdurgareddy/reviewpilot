"""Markdown for the PR review body and the inline comments."""

from __future__ import annotations

from .models import Category, FileDiff, Finding, Severity

ICON = {Severity.CRITICAL: "🔴", Severity.HIGH: "🟠", Severity.MEDIUM: "🟡", Severity.LOW: "🔵"}
LABEL = {Category.SECURITY: "Security", Category.BUG: "Bugs", Category.PERFORMANCE: "Performance",
         Category.TESTING: "Testing"}


def verdict_for(findings: list[Finding]) -> str:
    if any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in findings):
        return "request_changes"
    return "comment" if findings else "approve"


def render_summary(findings: list[Finding], files: list[FileDiff], degraded: list[str] | None = None) -> str:
    lines_added = sum(len(f.added_lines) for f in files)
    head = f"## ReviewPilot\n\nReviewed **{len(files)} file(s)**, **{lines_added} added line(s)**."
    if not findings:
        return head + "\n\n✅ No issues found by the security, bug, performance and testing agents."

    rows = []
    for cat in Category:
        cs = [f for f in findings if f.category == cat]
        counts = " ".join(f"{ICON[s]} {sum(1 for f in cs if f.severity == s)}" for s in Severity
                          if any(f.severity == s for f in cs))
        rows.append(f"| {LABEL[cat]} | {len(cs)} | {counts or '–'} |")
    top = sorted(findings, key=lambda f: (f.severity.rank, -f.confidence))[:5]
    out = [head, "", "| Agent | Findings | By severity |", "|---|---:|---|", *rows, "", "**Top issues**", ""]
    out += [f"- {ICON[f.severity]} **{f.title}** · `{f.file}:{f.line}`" for f in top]
    if degraded:
        out += ["", f"> ⚠️ The model was unavailable for: {', '.join(degraded)}. Those agents used static rules only."]
    return "\n".join(out)


def render_comment(f: Finding) -> str:
    body = [f"{ICON[f.severity]} **{f.title}** · {f.severity.value} · {LABEL[f.category].lower()}", "", f.message]
    if f.suggestion:
        sugg = f.suggestion.strip()
        body += ["", "**Suggested fix**", "", f"```\n{sugg}\n```" if "\n" in sugg or "(" in sugg else sugg]
    meta = f"{f.rule_id} · {f.source} · confidence {f.confidence:.2f}"
    body += ["", f"<sub>{meta}</sub>"]
    return "\n".join(body)
