"""A small async DAG runner for agent workflows.

Nodes declare which nodes they depend on. Every node whose dependencies are
done runs concurrently, and each run is recorded as a trace event (start/end
time, status) that the dashboard draws as a timeline. A failing optional node is
recorded and skipped rather than failing the whole review.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any

from .models import TraceEvent

NodeFn = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class Node:
    name: str
    fn: NodeFn
    deps: tuple[str, ...] = ()
    optional: bool = False


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)

    def add(self, name: str, fn: NodeFn, deps: tuple[str, ...] | list[str] = (), optional: bool = False) -> Graph:
        if name in self.nodes:
            raise ValueError(f"duplicate node {name}")
        self.nodes[name] = Node(name, fn, tuple(deps), optional)
        return self

    def validate(self) -> list[str]:
        """Return a topological order, or raise on unknown deps / cycles."""
        for n in self.nodes.values():
            for d in n.deps:
                if d not in self.nodes:
                    raise ValueError(f"{n.name} depends on unknown node {d}")
        order, seen, visiting = [], set(), set()

        def visit(name: str) -> None:
            if name in seen:
                return
            if name in visiting:
                raise ValueError(f"cycle at {name}")
            visiting.add(name)
            for d in self.nodes[name].deps:
                visit(d)
            visiting.discard(name)
            seen.add(name)
            order.append(name)

        for name in self.nodes:
            visit(name)
        return order

    async def run(self, state: dict[str, Any]) -> tuple[dict[str, Any], list[TraceEvent]]:
        self.validate()
        t0 = time.perf_counter()
        trace: list[TraceEvent] = []
        done: dict[str, asyncio.Event] = {n: asyncio.Event() for n in self.nodes}
        failed: set[str] = set()

        async def run_node(node: Node) -> None:
            await asyncio.gather(*(done[d].wait() for d in node.deps))
            start = (time.perf_counter() - t0) * 1000
            if any(d in failed for d in node.deps if not self.nodes[d].optional):
                failed.add(node.name)
                trace.append(TraceEvent(node.name, start, start, "skipped", "upstream failed"))
                done[node.name].set()
                return
            try:
                state[node.name] = await node.fn(state)
                trace.append(TraceEvent(node.name, start, (time.perf_counter() - t0) * 1000))
            except Exception as e:  # recorded in the trace
                failed.add(node.name)
                state[node.name] = None
                trace.append(TraceEvent(node.name, start, (time.perf_counter() - t0) * 1000, "error", repr(e)[:200]))
                if not node.optional:
                    done[node.name].set()
                    raise
            finally:
                done[node.name].set()

        await asyncio.gather(*(run_node(n) for n in self.nodes.values()))
        trace.sort(key=lambda e: (e.start_ms, e.node))
        return state, trace
