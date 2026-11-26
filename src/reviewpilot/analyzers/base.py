"""Rule engine for the deterministic analyzers.

Rules only look at *added* lines, so a PR is never blamed for code it didn't
touch. Some rules also need the surrounding hunk (for example "inside a loop" or
"inside an async function"), which ``LineContext`` provides.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..models import Category, FileDiff, Finding, Hunk, Line, Severity


@dataclass
class LineContext:
    file: FileDiff
    hunk: Hunk
    index: int                       # index of the line inside hunk.lines

    @property
    def line(self) -> Line:
        return self.hunk.lines[self.index]

    def preceding(self) -> list[Line]:
        """Lines before this one in the hunk (new-file view: context + added)."""
        return [ln for ln in self.hunk.lines[: self.index] if ln.kind != "-"]

    def indent(self, text: str | None = None) -> int:
        t = self.line.text if text is None else text
        return len(t) - len(t.lstrip())

    def enclosing(self, pattern: re.Pattern[str]) -> Line | None:
        """Nearest preceding line that matches ``pattern`` and is less indented."""
        ind = self.indent()
        for ln in reversed(self.preceding()):
            if not ln.text.strip():
                continue
            li = self.indent(ln.text)
            if li < ind and pattern.search(ln.text):
                return ln
            if li < ind:
                ind = li
                if pattern.search(ln.text):
                    return ln
        return None


@dataclass
class Rule:
    id: str
    category: Category
    severity: Severity
    title: str
    message: str
    pattern: re.Pattern[str] | None = None
    languages: tuple[str, ...] = ()            # empty = all languages
    suggestion: str | None = None
    confidence: float = 0.8
    when: Callable[[LineContext], bool] | None = None   # extra condition
    exclude: re.Pattern[str] | None = None
    skip_tests: bool = False

    def applies_to(self, fd: FileDiff) -> bool:
        if self.skip_tests and fd.is_test:
            return False
        return not self.languages or fd.language in self.languages

    def check(self, ctx: LineContext) -> Finding | None:
        text = ctx.line.text
        if _is_comment(text, ctx.file.language):
            return None
        if self.pattern is not None and not self.pattern.search(text):
            return None
        if self.exclude is not None and self.exclude.search(text):
            return None
        if self.when is not None and not self.when(ctx):
            return None
        return Finding(
            file=ctx.file.path, line=ctx.line.number, category=self.category, severity=self.severity,
            title=self.title, message=self.message, rule_id=self.id, suggestion=self.suggestion,
            confidence=self.confidence, source="static",
        )


@dataclass
class Analyzer:
    name: str
    category: Category
    rules: list[Rule] = field(default_factory=list)

    def run(self, files: Iterable[FileDiff]) -> list[Finding]:
        out: list[Finding] = []
        for fd in files:
            active = [r for r in self.rules if r.applies_to(fd)]
            if not active:
                continue
            for hunk in fd.hunks:
                for i, ln in enumerate(hunk.lines):
                    if ln.kind != "+":
                        continue
                    ctx = LineContext(fd, hunk, i)
                    for rule in active:
                        f = rule.check(ctx)
                        if f:
                            f.agent = self.name
                            out.append(f)
            out.extend(self.file_level(fd))
        return out

    def file_level(self, fd: FileDiff) -> list[Finding]:
        """Hook for rules that look at a whole file diff rather than one line."""
        return []


_COMMENT = {
    "python": ("#",), "ruby": ("#",), "shell": ("#",), "yaml": ("#",),
    "javascript": ("//", "/*", "*"), "typescript": ("//", "/*", "*"), "java": ("//", "/*", "*"),
    "go": ("//",), "csharp": ("//",), "kotlin": ("//",), "rust": ("//",), "php": ("//", "#"),
}


def _is_comment(text: str, language: str) -> bool:
    s = text.lstrip()
    return any(s.startswith(p) for p in _COMMENT.get(language, ()))


def rx(p: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(p, flags)
