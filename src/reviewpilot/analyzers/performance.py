"""Performance rules: N+1 queries, blocking calls in async code, quadratic patterns."""

from __future__ import annotations

from ..models import Category, Severity
from .base import Analyzer, LineContext, Rule, rx

P = Category.PERFORMANCE

_LOOP = rx(r"^\s*(for\b.*:\s*$|while\b.*:\s*$|for\s*\(|while\s*\(|\w+(\.\w+)*\.forEach\(|for\s+\w+\s+(of|in)\s+)")
_ASYNC_DEF = rx(r"^\s*async\s+def\b|\basync\s+function\b|\basync\s*\(|=\s*async\b")


def in_loop(ctx: LineContext) -> bool:
    return ctx.enclosing(_LOOP) is not None


def in_async(ctx: LineContext) -> bool:
    return ctx.enclosing(_ASYNC_DEF) is not None


RULES = [
    Rule("PERF001", P, Severity.HIGH, "Database query inside a loop (N+1)",
         "A query runs once per iteration; with N rows this makes N round trips to the database.",
         rx(r"(\.execute\(|\.query\(|\.objects\.(get|filter)\(|\.find(One|ById)?\(|\.findUnique\(|session\.get\(|\.fetchone\(|SELECT\b)", 0),
         when=in_loop,
         suggestion="Fetch everything in one query (e.g. `WHERE id IN (...)`, select_related / prefetch_related, or a JOIN).",
         confidence=0.82),
    Rule("PERF002", P, Severity.MEDIUM, "HTTP request inside a loop",
         "Sequential network calls in a loop are slow; latency adds up per item.",
         rx(r"requests\.(get|post|put|delete)\(|httpx\.(get|post)\(|\bfetch\(|axios\.(get|post)\("),
         when=in_loop,
         suggestion="Batch the requests, or run them concurrently (asyncio.gather / Promise.all).",
         confidence=0.72),
    Rule("PERF003", P, Severity.HIGH, "Blocking sleep in async code",
         "time.sleep blocks the whole event loop, stalling every other request.",
         rx(r"\btime\.sleep\("), languages=("python",), when=in_async,
         suggestion="Use `await asyncio.sleep(...)`.", confidence=0.93),
    Rule("PERF004", P, Severity.HIGH, "Blocking HTTP call in async code",
         "`requests` is synchronous and blocks the event loop inside an async function.",
         rx(r"\brequests\.(get|post|put|patch|delete|request)\("), languages=("python",), when=in_async,
         suggestion="Use an async client such as httpx.AsyncClient or aiohttp.", confidence=0.9),
    Rule("PERF005", P, Severity.MEDIUM, "String concatenation in a loop",
         "Repeated `+=` on strings copies the string each time (quadratic).",
         rx(r"""^\s*\w+\s*\+=\s*(.*["']|str\()"""), languages=("python", "java"), when=in_loop,
         suggestion="Collect parts in a list and `''.join(parts)` once (StringBuilder in Java).",
         confidence=0.7),
    Rule("PERF006", P, Severity.MEDIUM, "Sequential await inside a loop",
         "Each iteration waits for the previous one; independent calls can run concurrently.",
         rx(r"^\s*(const\s+\w+\s*=\s*|let\s+\w+\s*=\s*|\w+\s*=\s*)?await\b"),
         languages=("javascript", "typescript", "python"), when=in_loop,
         suggestion="Collect the promises and await them together (Promise.all / asyncio.gather).",
         confidence=0.62),
    Rule("PERF007", P, Severity.LOW, "Membership test on a list in a loop",
         "`x in some_list` is O(n); inside a loop this becomes O(n²).",
         rx(r"\bif\s+\w+\s+(not\s+)?in\s+\w+(_list|s)\b\s*:"), languages=("python",), when=in_loop,
         suggestion="Convert the list to a set once before the loop.", confidence=0.5),
    Rule("PERF008", P, Severity.MEDIUM, "Unbounded query",
         "Loading every row into memory will get slower and eventually fail as the table grows.",
         rx(r"\.objects\.all\(\)|\.findAll\(\s*\)|\.find\(\s*\{\s*\}\s*\)|SELECT\s+\*\s+FROM\s+\w+\s*[\"'`]?\s*\)?$", 0),
         suggestion="Paginate or add a LIMIT, and select only the columns you need.", confidence=0.55),
]


def make() -> Analyzer:
    return Analyzer("performance", P, list(RULES))
