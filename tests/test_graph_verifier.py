import asyncio
import time

import pytest

from reviewpilot.diff import parse_diff
from reviewpilot.graph import Graph
from reviewpilot.models import Category, Finding, Severity
from reviewpilot.verifier import VerifierConfig, verify
from conftest import new_file_diff


def test_independent_nodes_run_concurrently():
    async def slow(_):
        await asyncio.sleep(0.1)
        return 1

    g = Graph().add("a", slow)
    for n in "bcd":
        g.add(n, slow, deps=["a"])
    g.add("e", slow, deps=["b", "c", "d"])
    t0 = time.perf_counter()
    state, trace = asyncio.run(g.run({}))
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.45                      # 3 levels, not 5 sequential nodes
    assert [e.node for e in trace][0] == "a" and trace[-1].node == "e"


def test_cycles_and_unknown_deps_are_rejected():
    async def f(_):
        return None
    with pytest.raises(ValueError):
        Graph().add("a", f, deps=["b"]).add("b", f, deps=["a"]).validate()
    with pytest.raises(ValueError):
        Graph().add("a", f, deps=["missing"]).validate()


def test_optional_node_failure_is_recorded_not_fatal():
    async def boom(_):
        raise RuntimeError("agent crashed")

    async def ok(state):
        return "done"

    g = Graph().add("agent", boom, optional=True).add("after", ok, deps=["agent"])
    state, trace = asyncio.run(g.run({}))
    assert state["after"] == "done"
    assert {e.node: e.status for e in trace} == {"agent": "error", "after": "ok"}


def _f(line, sev=Severity.MEDIUM, conf=0.8, source="static", cat=Category.BUG):
    return Finding("a.py", line, cat, sev, f"t{line}", "m", "R", confidence=conf, source=source)


def test_verifier_filters_merges_and_ranks():
    files = parse_diff(new_file_diff("a.py", "\n".join(f"x{i} = {i}" for i in range(1, 6))))
    findings = [
        _f(2, Severity.LOW), _f(4, Severity.CRITICAL), _f(99),             # 99: not an added line
        _f(3, conf=0.2),                                                   # below threshold
        _f(2, Severity.HIGH, 0.7, "llm"),                                  # duplicate of line 2
        Finding("other.py", 1, Category.BUG, Severity.HIGH, "t", "m"),      # file not in diff
    ]
    kept, dropped = verify(findings, files)
    assert [(f.line, f.severity.value) for f in kept] == [(4, "critical"), (2, "high")]
    assert kept[1].source == "static+llm" and dropped == 4


def test_verifier_caps():
    files = parse_diff(new_file_diff("a.py", "\n".join(f"x{i} = {i}" for i in range(1, 30))))
    kept, dropped = verify([_f(i) for i in range(1, 30)], files, VerifierConfig(max_per_file=5))
    assert len(kept) == 5 and dropped == 24
