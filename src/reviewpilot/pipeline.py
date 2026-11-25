"""End-to-end review: diff text in, ranked findings + summary out.

    parse ─► route ─┬─► security ─┐
                    ├─► bugs ─────┤
                    ├─► performance ┼─► verify ─► summarize
                    └─► testing ──┘
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from .agents import AgentResult, make_agents
from .diff import parse_diff
from .graph import Graph
from .llm import LLMProvider, OfflineProvider
from .models import Category, FileDiff, ReviewResult, Severity, Usage
from .summary import render_summary, verdict_for
from .verifier import VerifierConfig, verify

CODE_LANGS = {"python", "javascript", "typescript", "java", "go", "ruby", "php", "csharp", "kotlin", "rust"}

DEFAULT_IGNORE = [
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "*.min.js", "*.min.css",
    "*.map", "dist/*", "build/*", "vendor/*", "node_modules/*", "*.snap", "*.svg", "*.png", "*.jpg",
    "*.pdf", "*.ipynb", "migrations/*",
]


@dataclass
class ReviewConfig:
    agents: list[str] = field(default_factory=lambda: ["security", "bugs", "performance", "testing"])
    ignore: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE))
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    max_files: int = 60


def route(files: list[FileDiff], agent: str) -> list[FileDiff]:
    """Which files each specialist sees. Security also scans config files for secrets."""
    if agent == "security":
        return files
    if agent == "testing":
        return [f for f in files if f.language in CODE_LANGS]
    return [f for f in files if f.language in CODE_LANGS and not f.is_test]


async def review_diff(diff_text: str, provider: LLMProvider | None = None,
                      config: ReviewConfig | None = None) -> ReviewResult:
    provider = provider or OfflineProvider()
    cfg = config or ReviewConfig()
    agents = {a.name: a for a in make_agents(provider, cfg.agents)}
    g = Graph()

    async def parse(state):
        files = parse_diff(state["diff"])
        files = [f for f in files if not any(fnmatch.fnmatch(f.path, p) or fnmatch.fnmatch(f.path.rsplit("/", 1)[-1], p)
                                             for p in cfg.ignore)]
        return files[: cfg.max_files]

    g.add("parse", parse)

    def specialist(name: str):
        async def run(state) -> AgentResult:
            return await agents[name].review(route(state["parse"], name))
        return run

    for name in agents:
        g.add(name, specialist(name), deps=["parse"], optional=True)

    async def verify_node(state):
        results = [state[n] for n in agents if state.get(n)]
        all_findings = [f for r in results for f in r.findings]
        kept, dropped = verify(all_findings, state["parse"], cfg.verifier)
        return kept, dropped + sum(r.rejected for r in results)

    g.add("verify", verify_node, deps=list(agents))

    async def summarize(state):
        kept, _ = state["verify"]
        return render_summary(kept, state["parse"], degraded=[n for n in agents if state.get(n) and state[n].degraded])

    g.add("summarize", summarize, deps=["verify"])

    state, trace = await g.run({"diff": diff_text})
    findings, dropped = state["verify"]
    usage = Usage()
    for n in agents:
        if state.get(n):
            usage.add(state[n].usage)
    files = state["parse"]
    return ReviewResult(
        findings=findings,
        files_reviewed=len(files),
        lines_added=sum(len(f.added_lines) for f in files),
        summary=state["summarize"],
        verdict=verdict_for(findings),
        usage=usage,
        trace=trace,
        dropped=dropped,
        model=provider.name,
    )


def count_by(findings, attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        k = getattr(f, attr).value
        out[k] = out.get(k, 0) + 1
    return out


__all__ = ["ReviewConfig", "review_diff", "route", "count_by", "Category", "Severity"]
