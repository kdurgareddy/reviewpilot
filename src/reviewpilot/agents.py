"""Specialist review agents.

Each agent pairs a deterministic analyzer with an LLM pass:

1. The analyzer flags candidate issues on added lines (cheap, precise for known patterns).
2. The LLM sees the numbered diff plus those candidates as *hints*. It confirms or
   rejects each hint and adds issues the rules can't see (logic errors, missing
   checks, races).
3. Rejected hints are dropped; confirmed ones are marked ``static+llm``.

With the offline provider only step 1 runs, which keeps tests deterministic.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

from .analyzers import ALL as ANALYZERS
from .analyzers import Analyzer
from .diff import render_numbered
from .llm import FINDINGS_SCHEMA, LLMProvider, OfflineProvider
from .models import Category, FileDiff, Finding, Severity, Usage

FOCUS = {
    "security": (
        Category.SECURITY,
        ("injection (SQL, command, template), authentication and authorisation gaps, secrets, unsafe "
        "deserialisation, SSRF, path traversal, XSS, weak crypto, missing input validation"),
    ),
    "bugs": (
        Category.BUG,
        ("logic errors, off-by-one, wrong conditions, null/None handling, unhandled errors, race conditions, "
        "resource leaks, incorrect async usage, type confusion, broken edge cases"),
    ),
    "performance": (
        Category.PERFORMANCE,
        ("N+1 queries, blocking calls in async code, needless work in loops, quadratic algorithms, unbounded "
        "memory, missing pagination or caching, chatty network calls"),
    ),
    "testing": (
        Category.TESTING,
        ("new or changed behaviour without tests, tests with no assertions, missing edge-case and failure tests, "
        "flaky patterns (sleeps, real network, time)"),
    ),
}

SYSTEM = """You are the {agent} reviewer on an automated code-review team.
Review ONLY the added lines (marked +) in the diff. Focus on: {focus}.

Rules:
- Report real, specific problems a senior engineer would flag. No style nits, no praise.
- `line` must be a line number from the left column of an added (+) line.
- Static-analysis hints are given below. For each hint, either confirm it by setting
  `confirms_rule` on a finding, or list its id in `rejected_hints` if it is a false positive.
- Calibrate `confidence`: 0.9+ only when you are sure; skip anything under 0.5.
- If there is nothing worth reporting, return an empty list."""


@dataclass
class AgentResult:
    agent: str
    findings: list[Finding]
    rejected: int = 0
    usage: Usage = field(default_factory=Usage)
    degraded: bool = False          # LLM failed; static findings only


class SpecialistAgent:
    def __init__(self, name: str, provider: LLMProvider, *, max_retries: int = 3, concurrency: int = 4,
                 max_chars: int = 24_000):
        if name not in FOCUS:
            raise ValueError(f"unknown agent {name}")
        self.name = name
        self.category, self.focus = FOCUS[name]
        self.analyzer: Analyzer = ANALYZERS[name]()
        self.provider = provider
        self.max_retries = max_retries
        self.sem = asyncio.Semaphore(concurrency)
        self.max_chars = max_chars

    @property
    def uses_llm(self) -> bool:
        return not isinstance(self.provider, OfflineProvider)

    async def review(self, files: list[FileDiff]) -> AgentResult:
        static = self.analyzer.run(files)
        for f in static:
            f.agent = self.name
        if not self.uses_llm or not files:
            return AgentResult(self.name, static)

        batches = self._batch(files)
        results = await asyncio.gather(*(self._review_batch(b, static) for b in batches), return_exceptions=True)

        out: list[Finding] = []
        usage = Usage()
        rejected = 0
        degraded = False
        for batch, res in zip(batches, results):
            paths = {f.path for f in batch}
            batch_static = [s for s in static if s.file in paths]
            if isinstance(res, BaseException):
                degraded = True
                out.extend(batch_static)          # fall back to the rules for this batch
                continue
            findings, rej, u = res
            out.extend(findings)
            rejected += rej
            usage.add(u)
        # findings for files that weren't sent (e.g. whole-PR test findings) stay as-is
        sent = {f.path for b in batches for f in b}
        out.extend(s for s in static if s.file not in sent)
        return AgentResult(self.name, out, rejected, usage, degraded)

    def _batch(self, files: list[FileDiff]) -> list[list[FileDiff]]:
        batches: list[list[FileDiff]] = [[]]
        size = 0
        for fd in files:
            n = len(render_numbered(fd))
            if batches[-1] and size + n > self.max_chars:
                batches.append([])
                size = 0
            batches[-1].append(fd)
            size += n
        return [b for b in batches if b]

    async def _review_batch(self, files: list[FileDiff], static: list[Finding]):
        paths = {f.path for f in files}
        hints = [s for s in static if s.file in paths]
        user = "\n\n".join(render_numbered(f) for f in files)
        if hints:
            user += "\n\nStatic-analysis hints:\n" + "\n".join(
                f"- [{h.rule_id}@{h.file}:{h.line}] {h.title}: {h.message}" for h in hints)
        system = SYSTEM.format(agent=self.name, focus=self.focus)

        async with self.sem:
            resp = await self._call_with_retry(system, user)
        return self._merge(resp.data, hints, files), len(resp.data.get("rejected_hints", [])), resp.usage

    async def _call_with_retry(self, system: str, user: str):
        delay = 0.5
        for attempt in range(self.max_retries):
            try:
                return await self.provider.complete_json(system, user, FINDINGS_SCHEMA)
            except (ConnectionError, TimeoutError):
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(delay * (0.5 + random.random()))
                delay *= 2
        raise RuntimeError("unreachable")

    def _merge(self, data: dict[str, Any], hints: list[Finding], files: list[FileDiff]) -> list[Finding]:
        rejected = {str(r).strip() for r in data.get("rejected_hints", [])}
        by_id = {f"{h.rule_id}@{h.file}:{h.line}": h for h in hints}
        default_file = files[0].path if len(files) == 1 else None
        line_to_file = {}
        for fd in files:
            for n in fd.added_lines:
                line_to_file.setdefault(n, fd.path)

        out: list[Finding] = []
        confirmed: set[str] = set()
        for item in data.get("findings", []):
            try:
                line = int(item["line"])
                sev = Severity(str(item.get("severity", "medium")).lower())
            except (KeyError, ValueError):
                continue
            file = item.get("file") or default_file or line_to_file.get(line)
            if not file:
                continue
            rule = str(item.get("confirms_rule") or "")
            hint = next((h for k, h in by_id.items() if rule and (k.startswith(rule + "@") or k == rule)
                         and h.file == file and abs(h.line - line) <= 2), None)
            if hint:
                key = f"{hint.rule_id}@{hint.file}:{hint.line}"
                confirmed.add(key)
                hint.source = "static+llm"
                hint.confidence = min(0.99, max(hint.confidence, float(item.get("confidence", 0.8))) + 0.05)
                if item.get("message"):
                    hint.message = str(item["message"])
                if item.get("suggestion"):
                    hint.suggestion = str(item["suggestion"])
                out.append(hint)
                continue
            out.append(Finding(
                file=file, line=line, category=self.category, severity=sev,
                title=str(item.get("title", "Issue"))[:120], message=str(item.get("message", "")),
                suggestion=item.get("suggestion") or None, confidence=float(item.get("confidence", 0.7)),
                source="llm", agent=self.name, rule_id=f"LLM-{self.name[:3].upper()}",
            ))
        for key, h in by_id.items():
            if key in confirmed:
                continue
            if key in rejected or h.rule_id in rejected:
                continue
            out.append(h)        # neither confirmed nor rejected: keep the rule's finding
        return out


def make_agents(provider: LLMProvider, names: list[str] | None = None) -> list[SpecialistAgent]:
    return [SpecialistAgent(n, provider) for n in (names or list(FOCUS))]
