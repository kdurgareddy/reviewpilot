"""Test-coverage rules: new logic without tests, tests without assertions."""

from __future__ import annotations

import re
from typing import Iterable

from ..models import Category, FileDiff, Finding, Severity
from .base import Analyzer

T = Category.TESTING

_DEF = {
    "python": re.compile(r"^\s*(async\s+)?def\s+(?!_)(\w+)\s*\("),
    "javascript": re.compile(r"^\s*export\s+(async\s+)?function\s+(\w+)|^\s*export\s+const\s+(\w+)\s*=\s*(async\s*)?\("),
    "typescript": re.compile(r"^\s*export\s+(async\s+)?function\s+(\w+)|^\s*export\s+const\s+(\w+)\s*=\s*(async\s*)?\("),
    "java": re.compile(r"^\s*public\s+(static\s+)?[\w<>\[\],\s]+\s+(\w+)\s*\("),
    "go": re.compile(r"^func\s+(\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)\s*\("),
}
_ASSERT = re.compile(r"\b(assert|expect\(|assertEquals|assertThat|assertTrue|should\.|pytest\.raises|toEqual|toBe)\b")
_TEST_FN = re.compile(r"^\s*(async\s+)?def\s+test_\w+|^\s*(it|test)\s*\(\s*['\"]|@Test\b")


class TestingAnalyzer(Analyzer):
    """Works at the level of the whole PR, since coverage is about which files changed together."""

    def run(self, files: Iterable[FileDiff]) -> list[Finding]:
        files = list(files)
        tests_touched = [f for f in files if f.is_test]
        out: list[Finding] = []

        for fd in files:
            if fd.is_test:
                out.extend(self._weak_tests(fd))
                continue
            pat = _DEF.get(fd.language)
            if not pat:
                continue
            new_defs = []
            for h in fd.hunks:
                for ln in h.added:
                    m = pat.match(ln.text)
                    if m:
                        name = next((g for g in m.groups()[1:] if g and g.strip() and not g.strip().startswith("(")), None)
                        if name and name not in ("main", "__init__"):
                            new_defs.append((ln.number, name))
            if not new_defs:
                continue
            stem = fd.path.rsplit("/", 1)[-1].split(".")[0]
            covered = any(stem in t.path or any(n in "".join(t.added_lines.values()) for _, n in new_defs)
                          for t in tests_touched)
            if not covered:
                line, name = new_defs[0]
                names = ", ".join(n for _, n in new_defs[:4]) + ("…" if len(new_defs) > 4 else "")
                out.append(Finding(
                    file=fd.path, line=line, category=T, severity=Severity.MEDIUM,
                    title="New code without tests",
                    message=f"This PR adds {len(new_defs)} public function(s) ({names}) but no test file covers them.",
                    rule_id="TEST001", confidence=0.7, agent=self.name,
                    suggestion=f"Add tests for `{name}` covering the normal case, edge cases and errors.",
                ))
        return out

    def _weak_tests(self, fd: FileDiff) -> list[Finding]:
        out: list[Finding] = []
        for h in fd.hunks:
            lines = [ln for ln in h.lines if ln.kind != "-"]
            for i, ln in enumerate(lines):
                if ln.kind != "+" or not _TEST_FN.search(ln.text):
                    continue
                indent = len(ln.text) - len(ln.text.lstrip())
                body = []
                for nxt in lines[i + 1:]:
                    if nxt.text.strip() and (len(nxt.text) - len(nxt.text.lstrip())) <= indent and fd.language == "python":
                        break
                    if _TEST_FN.search(nxt.text):
                        break
                    body.append(nxt.text)
                if body and not any(_ASSERT.search(b) for b in body):
                    out.append(Finding(
                        file=fd.path, line=ln.number, category=T, severity=Severity.LOW,
                        title="Test without assertions",
                        message="This test runs code but never checks the result, so it can't fail on wrong behaviour.",
                        rule_id="TEST002", confidence=0.75, agent=self.name,
                        suggestion="Assert on the return value or side effect.",
                    ))
        return out


def make() -> Analyzer:
    return TestingAnalyzer("testing", T, [])
