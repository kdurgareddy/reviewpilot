"""Benchmark: precision and recall of the review pipeline on hand-labelled cases.

Each case is a source file under ``eval/cases``. A line that should be flagged
carries a trailing marker such as ``# expect: security`` (or ``// expect: bug``).
Markers are stripped before review, so the model never sees them. Files with no
markers are clean code, used to measure false positives.

A prediction matches a label when it is in the same file and category and within
one line of it.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .llm import OfflineProvider, provider_from_env
from .pipeline import ReviewConfig, review_diff

MARK = re.compile(r"\s*(#|//)\s*expect:\s*([a-z, ]+)\s*$")
CATS = ("security", "bug", "performance")
# Test coverage is judged per pull request (which files changed together), so the
# single-file benchmark leaves the testing agent out; unit tests cover it instead.
EVAL_CONFIG = ReviewConfig(agents=["security", "bugs", "performance"])


@dataclass
class Case:
    path: str
    source: str
    expected: list[tuple[int, str]]

    def as_diff(self) -> str:
        lines = self.source.splitlines()
        body = "\n".join("+" + ln for ln in lines)
        return (f"diff --git a/{self.path} b/{self.path}\nnew file mode 100644\n--- /dev/null\n+++ b/{self.path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n{body}\n")


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class Report:
    model: str
    cases: int
    labels: int
    per_category: dict[str, Score] = field(default_factory=dict)
    overall: Score = field(default_factory=Score)
    clean_cases: int = 0
    clean_false_positives: int = 0
    seconds: float = 0.0
    misses: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def s(x: Score) -> dict:
            return {"tp": x.tp, "fp": x.fp, "fn": x.fn, "precision": round(x.precision, 3),
                    "recall": round(x.recall, 3), "f1": round(x.f1, 3)}
        return {"model": self.model, "cases": self.cases, "labels": self.labels,
                "overall": s(self.overall), "per_category": {k: s(v) for k, v in self.per_category.items()},
                "clean_cases": self.clean_cases, "clean_false_positives": self.clean_false_positives,
                "seconds": round(self.seconds, 2), "misses": self.misses, "false_positives": self.false_positives}


def load_cases(root: str | Path) -> list[Case]:
    cases = []
    root = Path(root)
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith(".") or p.suffix == ".md":
            continue
        rel = p.relative_to(root).as_posix()
        clean, expected = [], []
        for i, raw in enumerate(p.read_text().splitlines(), start=1):
            m = MARK.search(raw)
            if m:
                for cat in m.group(2).replace(" ", "").split(","):
                    if cat not in CATS:
                        raise ValueError(f"{rel}:{i}: unknown category {cat!r}")
                    expected.append((i, cat))
                raw = raw[: m.start()]
            clean.append(raw)
        cases.append(Case(rel, "\n".join(clean) + "\n", expected))
    return cases


async def evaluate(cases: list[Case], provider=None) -> Report:
    provider = provider or OfflineProvider()
    rep = Report(model=provider.name, cases=len(cases), labels=sum(len(c.expected) for c in cases),
                 per_category={c: Score() for c in CATS})
    t0 = time.perf_counter()
    for case in cases:
        result = await review_diff(case.as_diff(), provider, EVAL_CONFIG)
        preds = [(f.line, f.category.value, f) for f in result.findings]
        unmatched = list(case.expected)
        if not case.expected:
            rep.clean_cases += 1
            rep.clean_false_positives += len(preds)
        for line, cat, f in preds:
            hit = next((e for e in unmatched if e[1] == cat and abs(e[0] - line) <= 1), None)
            if hit:
                unmatched.remove(hit)
                rep.per_category[cat].tp += 1
            else:
                rep.per_category[cat].fp += 1
                rep.false_positives.append(f"{case.path}:{line} {cat} {f.rule_id} {f.title}")
        for line, cat in unmatched:
            rep.per_category[cat].fn += 1
            rep.misses.append(f"{case.path}:{line} {cat}")
    for s in rep.per_category.values():
        rep.overall.tp += s.tp
        rep.overall.fp += s.fp
        rep.overall.fn += s.fn
    rep.seconds = time.perf_counter() - t0
    return rep


def format_report(rep: Report) -> str:
    out = [f"ReviewPilot benchmark · model: {rep.model} · {rep.cases} cases · {rep.labels} labelled issues", "",
           f"{'category':<12} {'precision':>9} {'recall':>7} {'f1':>6}   tp  fp  fn", "-" * 52]
    for cat, s in rep.per_category.items():
        out.append(f"{cat:<12} {s.precision:>9.2f} {s.recall:>7.2f} {s.f1:>6.2f} {s.tp:>4} {s.fp:>3} {s.fn:>3}")
    o = rep.overall
    out += ["-" * 52, f"{'overall':<12} {o.precision:>9.2f} {o.recall:>7.2f} {o.f1:>6.2f} {o.tp:>4} {o.fp:>3} {o.fn:>3}",
            "", f"clean files: {rep.clean_cases}, false positives on them: {rep.clean_false_positives}",
            f"time: {rep.seconds:.2f}s"]
    if rep.misses:
        out += ["", "missed:"] + [f"  {m}" for m in rep.misses]
    if rep.false_positives:
        out += ["", "false positives:"] + [f"  {m}" for m in rep.false_positives]
    return "\n".join(out)


def main(cases_dir: str, offline: bool = False, json_out: str | None = None) -> int:
    provider = OfflineProvider() if offline else provider_from_env()
    rep = asyncio.run(evaluate(load_cases(cases_dir), provider))
    print(format_report(rep))
    if json_out:
        Path(json_out).write_text(json.dumps(rep.to_dict(), indent=2))
    return 0
