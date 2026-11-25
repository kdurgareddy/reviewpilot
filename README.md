# ReviewPilot

**Multi-agent AI code review for pull requests.** Four specialist agents (security, bugs, performance, testing) review every PR in parallel. A verifier filters their findings, and the results are posted to GitHub as inline review comments with suggested fixes.

```
            ┌───────────────┐
 PR opened ─►  GitHub App /  │  webhook (HMAC-verified) or GitHub Action
            │  Action / CLI  │
            └──────┬────────┘
                   ▼
                 parse ── unified diff → files, hunks, new-file line numbers
                   │
                 route ── each agent sees only the files it should
       ┌───────────┼────────────┬─────────────┐
       ▼           ▼            ▼             ▼
   security       bugs     performance     testing      run concurrently (async DAG)
   rules + LLM  rules + LLM  rules + LLM   PR-level coverage
       └───────────┴─────┬──────┴─────────────┘
                         ▼
                      verify ── drop hallucinated lines, merge duplicates,
                         │      confidence threshold, rank by severity
                         ▼
                    summarize ─► inline review comments · SARIF · dashboard · MCP
```

## Why it's built this way

- **Rules and an LLM working together.** Each agent runs deterministic rules first (precise and free), then gives the model the numbered diff *plus* the rule hits as hints. The model confirms or rejects each hint and adds issues rules can't see: logic errors, missing authorisation, off-by-one bugs. Confirmed hints are marked `static+llm`; rejected ones are dropped.
- **A verifier stage.** LLMs sometimes point at lines that aren't in the diff. Every finding must land on an *added* line, or it's discarded. Duplicates from different agents are merged, low-confidence findings are filtered, and output is capped so a PR never gets 200 comments.
- **Graceful degradation.** If the model is down or rate-limited, calls are retried with exponential backoff and jitter. If the model is still unavailable, that agent falls back to its rules and the review says so; the PR still gets reviewed.
- **Measured, not guessed.** A hand-labelled benchmark computes precision and recall per category, and CI fails if a change makes them worse.

## Benchmark

`reviewpilot eval` reviews 15 files (Python, TypeScript and Java) with 39 labelled issues, including clean files that should produce no findings.

| Mode | Precision | Recall | F1 | False positives on clean files |
|---|---:|---:|---:|---:|
| Static rules only (`--offline`) | **1.00** | **0.87** | **0.93** | 0 |
| Rules + LLM | run `reviewpilot eval` with your key | | | |

The five issues the rules miss are logic bugs: an off-by-one in a sliding window, a divide-by-zero on empty input, a wrong last-page calculation, `size()` used as a last index, and an admin endpoint with no authorisation check. Pattern matching can't catch these, and they are what the LLM layer is for. CI runs the LLM benchmark automatically when an `ANTHROPIC_API_KEY` secret is configured.

> The benchmark is small and was written alongside the rules, so treat the rules-only numbers as a regression gate, not a claim about real-world accuracy. New cases are welcome: add a file under `eval/cases/` and mark lines with `# expect: <category>`.

## What it catches

| Agent | Examples |
|---|---|
| **Security** | SQL injection (f-strings, `+`, `%`, `.format`, template literals), command injection (`shell=True`, `exec`), `eval`, unsafe `pickle`/`yaml.load`, hard-coded and live API keys (AWS, Stripe, GitHub, Slack, OpenAI), private keys, weak hashes, TLS verification off, unverified JWTs, XSS sinks, debug mode, wildcard CORS |
| **Bugs** | bare and swallowed exceptions, empty `catch {}`, mutable default arguments, `== None`, `is` with literals, `return` in `finally`, loose `==` in JS/TS, files opened without `with`, floating promises |
| **Performance** | N+1 queries in loops, HTTP calls in loops, `time.sleep` / `requests` inside `async def`, sequential `await` in loops, quadratic string building, unbounded queries |
| **Testing** | new public functions without tests in the same PR, tests with no assertions |
| **LLM layer** | logic and edge-case bugs, missing authorisation, race conditions, wrong error handling, anything the rules can't express |

Supports Python, JavaScript/TypeScript, Java, Go, C#, Kotlin, Ruby and PHP, and scans YAML and JSON config for secrets. Lockfiles, minified bundles, build output and vendored code are skipped.

## Quick start

```bash
pip install -e ".[dev]"

# Review any diff (static agents only, no key needed)
git diff main | reviewpilot review --offline

# With Claude or OpenAI
export ANTHROPIC_API_KEY=sk-ant-...      # or OPENAI_API_KEY=...
git diff main | reviewpilot review

# Other outputs
reviewpilot review changes.diff --format json        # machine-readable
reviewpilot review changes.diff --format sarif       # GitHub code scanning
reviewpilot review changes.diff --fail-on high       # exit 1 for CI gates

# Dashboard + API at http://localhost:8000
reviewpilot serve
```

Try it on the bundled example PR:

```bash
reviewpilot review examples/sample.diff --offline
```

```
critical app/orders.py:19  SQL built from string formatting  [SEC004, static]
critical app/orders.py:13  SQL built from string formatting  [SEC004, static]
high     app/orders.py:27  Blocking sleep in async code  [PERF003, static]
high     app/orders.py:26  Blocking HTTP call in async code  [PERF004, static]
high     app/orders.py:33  Exception silently swallowed  [BUG002, static]
high     app/orders.py:25  Database query inside a loop (N+1)  [PERF001, static]
...
14 finding(s) in 2 file(s), 41 added line(s) · verdict: request_changes
```

## Four ways to run it

### 1. GitHub Action (easiest)

```yaml
# .github/workflows/reviewpilot.yml
on: pull_request
permissions: { contents: read, pull-requests: write, security-events: write }
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: kdurgareddy/reviewpilot@main
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}   # optional
          fail-on: critical                                      # optional
```

It posts an inline review on the PR and uploads SARIF to the **Security → Code scanning** tab. This repo reviews its own pull requests the same way.

### 2. GitHub App (organisation-wide)

Run the server (`docker compose up`), create a GitHub App pointing its webhook at `https://your-host/webhooks/github`, and install it on your repos. Every opened or updated PR is reviewed automatically as `reviewpilot[bot]`, with a commit status. See [docs/github-app.md](docs/github-app.md).

### 3. MCP server (inside your editor)

Let Claude Desktop, Claude Code or Cursor review your changes before you push:

```json
{ "mcpServers": { "reviewpilot": { "command": "reviewpilot", "args": ["mcp"] } } }
```

Tools: `review_diff`, `review_working_tree` (runs `git diff` on a local repo) and `list_rules`.

### 4. Dashboard and REST API

`reviewpilot serve` starts a playground where you paste a diff and see each agent's findings, the agent execution timeline and GitHub-style inline comments, plus a history of past reviews.

| Method | Path | |
|---|---|---|
| `POST` | `/api/review` | Review a diff: `{"diff": "...", "repo": "acme/shop"}` |
| `GET` | `/api/reviews` · `/api/reviews/{id}` | Review history |
| `GET` | `/api/stats` | Totals by category and severity |
| `POST` | `/webhooks/github` | GitHub App webhook (HMAC-SHA256 verified) |
| `GET` | `/health` | Liveness and active model |

## Configuration

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | unset | Enables the LLM layer (Anthropic is preferred if both are set) |
| `REVIEWPILOT_PROVIDER` | auto | Force `anthropic`, `openai` or empty for static only |
| `REVIEWPILOT_MODEL` | `claude-sonnet-4-5` / `gpt-4.1-mini` | Model name |
| `OPENAI_BASE_URL` | OpenAI | Any OpenAI-compatible endpoint (Azure OpenAI, local vLLM, Ollama) |
| `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET` | | GitHub App mode |
| `REVIEWPILOT_DB` | `reviewpilot.db` | SQLite path for history |

## Project layout

```
src/reviewpilot/
  diff.py          unified-diff parser (new-file line numbers, renames, multi-hunk)
  analyzers/       rule engines: security, bugs, performance, testing
  agents.py        specialist agents: rules + LLM, hint confirm/reject, retries, fallback
  llm.py           Claude (tool use) / OpenAI (JSON schema) providers, response cache
  graph.py         async DAG runner with per-node tracing
  verifier.py      critic stage: grounding, dedupe, threshold, ranking, caps
  pipeline.py      wires the graph together
  github.py        webhook verification, App JWT auth, review posting with 422 fallback
  api.py           FastAPI service · static/index.html dashboard
  mcp_server.py    Model Context Protocol server (stdio)
  sarif.py         SARIF 2.1.0 export
  evaluate.py      benchmark runner (precision / recall / F1)
eval/cases/        labelled benchmark files
tests/             unit and integration tests (pytest)
action.yml         GitHub Action
```

## Development

```bash
pip install -e ".[dev]"
pytest -q                     # unit + integration tests, includes the benchmark regression gate
reviewpilot eval --offline    # benchmark report
ruff check src tests
```

## Roadmap

- tree-sitter parsing for function-level context in every language
- learn from 👍 / 👎 reactions on comments to tune per-repo thresholds
- incremental reviews that only look at commits added since the last review

MIT licensed.
