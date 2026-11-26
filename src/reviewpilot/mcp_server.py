"""Model Context Protocol server (stdio), so Claude Desktop, Claude Code or Cursor can
call ReviewPilot as a tool while you code.

Configure in an MCP client, e.g. Claude Desktop's config:

    {"mcpServers": {"reviewpilot": {"command": "reviewpilot", "args": ["mcp"]}}}
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from . import __version__
from .analyzers import ALL as ANALYZERS
from .llm import provider_from_env
from .pipeline import review_diff
from .summary import render_comment

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "review_diff",
        "description": "Review a unified diff with the security, bug, performance and testing agents. "
                       "Returns ranked findings with file, line, severity and a suggested fix.",
        "inputSchema": {"type": "object", "properties": {
            "diff": {"type": "string", "description": "Unified diff text (output of `git diff`)."}},
            "required": ["diff"]},
    },
    {
        "name": "review_working_tree",
        "description": "Review uncommitted changes in a local git repository (`git diff HEAD`).",
        "inputSchema": {"type": "object", "properties": {
            "repo_path": {"type": "string", "description": "Path to the git repository."},
            "base": {"type": "string", "description": "Ref to diff against (default HEAD)."}},
            "required": ["repo_path"]},
    },
    {
        "name": "list_rules",
        "description": "List the static rules each agent uses, with ids and severities.",
        "inputSchema": {"type": "object", "properties": {
            "agent": {"type": "string", "enum": list(ANALYZERS)}}},
    },
]


def _rules(agent: str | None) -> str:
    out = []
    for name, make in ANALYZERS.items():
        if agent and name != agent:
            continue
        a = make()
        out.append(f"## {name}")
        out += [f"- {r.id} ({r.severity.value}): {r.title}" for r in a.rules] or ["- (whole-PR coverage checks)"]
    return "\n".join(out)


async def _review(diff: str) -> str:
    result = await review_diff(diff, provider_from_env())
    if not result.findings:
        return result.summary
    parts = [result.summary, ""]
    for f in result.findings:
        parts += [f"### {f.file}:{f.line}", render_comment(f), ""]
    return "\n".join(parts)


async def call_tool(name: str, args: dict[str, Any]) -> str:
    if name == "review_diff":
        return await _review(args["diff"])
    if name == "review_working_tree":
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", args["repo_path"], "diff", args.get("base") or "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git diff failed: {err.decode().strip()}")
        diff = out.decode()
        return await _review(diff) if diff.strip() else "No uncommitted changes."
    if name == "list_rules":
        return _rules(args.get("agent"))
    raise KeyError(name)


async def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        return _ok(mid, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "reviewpilot", "version": __version__}})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        try:
            text = await call_tool(params.get("name", ""), params.get("arguments") or {})
            return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except KeyError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool or argument: {e}"}}
        except Exception as e:  # reported to the client in-band
            return _ok(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def _ok(mid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


async def serve() -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while line := await reader.readline():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = await handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


def main() -> None:
    asyncio.run(serve())
