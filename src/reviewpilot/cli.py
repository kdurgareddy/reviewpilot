"""Command line: review a diff, post to a PR, run the server, MCP server, or eval."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .llm import OfflineProvider, provider_from_env
from .models import Severity
from .pipeline import review_diff
from .sarif import to_sarif

COLOR = {"critical": "\033[1;31m", "high": "\033[31m", "medium": "\033[33m", "low": "\033[36m"}
RESET = "\033[0m"


def _read(src: str) -> str:
    return sys.stdin.read() if src == "-" else Path(src).read_text()


def _text(result, color: bool) -> str:
    out = []
    for f in result.findings:
        sev = f"{COLOR[f.severity.value]}{f.severity.value:<8}{RESET}" if color else f"{f.severity.value:<8}"
        out.append(f"{sev} {f.file}:{f.line}  {f.title}  [{f.rule_id}, {f.source}]")
        out.append(f"         {f.message}")
        if f.suggestion:
            out.append(f"         fix: {f.suggestion.splitlines()[0]}")
    out.append("")
    out.append(f"{len(result.findings)} finding(s) in {result.files_reviewed} file(s), "
               f"{result.lines_added} added line(s) · verdict: {result.verdict} · model: {result.model}")
    if result.usage.calls:
        out.append(f"tokens: {result.usage.input_tokens} in / {result.usage.output_tokens} out "
                   f"over {result.usage.calls} call(s)")
    return "\n".join(out)


async def _cmd_review(a: argparse.Namespace) -> int:
    provider = OfflineProvider() if a.offline else provider_from_env()
    result = await review_diff(_read(a.diff), provider)

    if a.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    elif a.format == "sarif":
        print(json.dumps(to_sarif(result), indent=2))
    elif a.format == "markdown":
        print(result.summary)
    else:
        print(_text(result, sys.stdout.isatty()))

    if a.github_pr:
        from .github import GitHubClient, build_review_payload

        repo, num = a.github_pr.split("#")
        gh = GitHubClient(os.environ["GITHUB_TOKEN"])
        await gh.post_review(repo, int(num), build_review_payload(result, a.sha or os.environ.get("GITHUB_SHA", "")))
        print(f"posted review to {repo}#{num}", file=sys.stderr)

    if a.fail_on:
        threshold = Severity(a.fail_on).rank
        if any(f.severity.rank <= threshold for f in result.findings):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reviewpilot", description="Multi-agent AI code review.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="review a unified diff (file path or - for stdin)")
    r.add_argument("diff", nargs="?", default="-")
    r.add_argument("--format", choices=["text", "json", "markdown", "sarif"], default="text")
    r.add_argument("--offline", action="store_true", help="static rules only, no LLM calls")
    r.add_argument("--fail-on", choices=[s.value for s in Severity], help="exit 1 at or above this severity")
    r.add_argument("--github-pr", metavar="OWNER/REPO#N", help="post the review to this pull request")
    r.add_argument("--sha", help="head commit SHA for the review (defaults to $GITHUB_SHA)")

    s = sub.add_parser("serve", help="run the API, webhook and dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    sub.add_parser("mcp", help="run the MCP server on stdio")

    e = sub.add_parser("eval", help="run the benchmark and print precision / recall")
    e.add_argument("--cases", default=str(Path(__file__).resolve().parents[2] / "eval" / "cases"))
    e.add_argument("--offline", action="store_true")
    e.add_argument("--json", dest="json_out")

    a = p.parse_args(argv)
    if a.cmd == "review":
        return asyncio.run(_cmd_review(a))
    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("reviewpilot.api:app", host=a.host, port=a.port)
        return 0
    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main()
        return 0
    if a.cmd == "eval":
        from .evaluate import main as eval_main

        return eval_main(a.cases, offline=a.offline, json_out=a.json_out)
    return 2


if __name__ == "__main__":
    sys.exit(main())
