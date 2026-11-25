"""Correctness rules: silent failures, Python gotchas, resource leaks."""

from __future__ import annotations

import re

from ..models import Category, Severity
from .base import Analyzer, LineContext, Rule, rx

B = Category.BUG


def _next_is_pass(ctx: LineContext) -> bool:
    """`except ...:` followed by a bare `pass` (or `...`)."""
    lines = [ln for ln in ctx.hunk.lines[ctx.index + 1:] if ln.kind != "-" and ln.text.strip()]
    return bool(lines) and lines[0].text.strip() in ("pass", "...", "continue")


def _not_in_with(ctx: LineContext) -> bool:
    return "with " not in ctx.line.text and not re.search(r"\bwith\b", ctx.line.text)


RULES = [
    Rule("BUG001", B, Severity.MEDIUM, "Bare except",
         "A bare `except:` also catches KeyboardInterrupt and SystemExit and hides real errors.",
         rx(r"^\s*except\s*:\s*(#.*)?$"), languages=("python",),
         suggestion="Catch the specific exception, e.g. `except ValueError:`.", confidence=0.9),
    Rule("BUG002", B, Severity.HIGH, "Exception silently swallowed",
         "The exception is caught and ignored, so failures will go unnoticed.",
         rx(r"^\s*except\b.*:\s*$"), languages=("python",), when=_next_is_pass,
         suggestion="Log the error or re-raise it; don't `pass`.", confidence=0.85),
    Rule("BUG003", B, Severity.HIGH, "Empty catch block",
         "The exception is caught and ignored, so failures will go unnoticed.",
         rx(r"catch\s*\([^)]*\)\s*\{\s*\}|\.catch\(\s*\(\s*\w*\s*\)\s*=>\s*\{\s*\}\s*\)"),
         languages=("java", "javascript", "typescript", "csharp", "kotlin"),
         suggestion="Handle the error: log it, rethrow it, or return a failure.", confidence=0.88),
    Rule("BUG004", B, Severity.MEDIUM, "Mutable default argument",
         "Default values are created once, so this list/dict is shared between calls.",
         rx(r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|set\(\)|list\(\)|dict\(\))"), languages=("python",),
         suggestion="Default to None and create the object inside: `items=None` then `items = items or []`.",
         confidence=0.92),
    Rule("BUG005", B, Severity.LOW, "Comparison to None with ==",
         "`== None` can be overridden by __eq__; use identity comparison.",
         rx(r"[!=]=\s*None\b"), languages=("python",), suggestion="Use `is None` / `is not None`.",
         confidence=0.8),
    Rule("BUG006", B, Severity.MEDIUM, "Identity comparison with a literal",
         "`is` compares object identity, not value; this only works by accident for small ints/strings.",
         rx(r"""\bis\s+(not\s+)?(-?\d+|["'][^"']*["'])(?=\s|\)|:|$)"""), languages=("python",),
         suggestion="Use `==` / `!=` for value comparison.", confidence=0.88),
    Rule("BUG007", B, Severity.LOW, "File opened without a context manager",
         "The file handle may leak if an exception is raised before close().",
         rx(r"(?<![\w.])open\s*\("), languages=("python",), when=_not_in_with, exclude=rx(r"^\s*return\b|webbrowser"),
         suggestion="Use `with open(path) as f:` so the file is always closed.", confidence=0.6),
    Rule("BUG008", B, Severity.MEDIUM, "Loose equality",
         "`==` coerces types (e.g. `0 == ''` is true); use strict equality.",
         rx(r"[^=!<>]==[^=]|!=[^=]"), languages=("javascript", "typescript"),
         exclude=rx(r"===|!==|==\s*null\b|!=\s*null\b"),
         suggestion="Use `===` / `!==`.", confidence=0.65),
    Rule("BUG009", B, Severity.MEDIUM, "assert used for runtime validation",
         "Asserts are stripped with `python -O`, so this check disappears in optimised runs.",
         rx(r"^\s*assert\s+(?!.*#\s*noqa)"), languages=("python",), skip_tests=True,
         suggestion="Raise an explicit exception, e.g. `if not ok: raise ValueError(...)`.", confidence=0.6),
    Rule("BUG010", B, Severity.HIGH, "Return inside finally",
         "A `return` in `finally` swallows any exception raised in the try block.",
         rx(r"^\s*return\b"), languages=("python", "java", "javascript", "typescript"),
         when=lambda c: c.enclosing(rx(r"^\s*(finally\s*:|}\s*finally\s*\{|finally\s*\{)")) is not None,
         confidence=0.85, suggestion="Move the return after the try/finally block."),
    Rule("BUG011", B, Severity.MEDIUM, "Floating promise",
         "An async call is not awaited, so errors are lost and ordering is not guaranteed.",
         rx(r"^\s*(?!return|await|const|let|var|yield)\w+(\.\w+)*\.(save|send|write|fetch|update|delete|create)\w*\("),
         languages=("javascript", "typescript"),
         when=lambda c: c.enclosing(rx(r"\basync\b")) is not None,
         suggestion="`await` the call (or explicitly handle the promise).", confidence=0.55),
]


def make() -> Analyzer:
    return Analyzer("bugs", B, list(RULES))
