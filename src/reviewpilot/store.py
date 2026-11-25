"""SQLite persistence for reviews, so the dashboard can show history and trends."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import ReviewResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo TEXT NOT NULL,
  pr_number INTEGER,
  title TEXT,
  commit_sha TEXT,
  verdict TEXT NOT NULL,
  files_reviewed INTEGER NOT NULL,
  lines_added INTEGER NOT NULL,
  finding_count INTEGER NOT NULL,
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  duration_ms REAL,
  result_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_repo ON reviews(repo, created_at DESC);
"""


class Store:
    def __init__(self, path: str | Path = "reviewpilot.db"):
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def save(self, result: ReviewResult, *, repo: str, pr_number: int | None = None, title: str = "",
             commit_sha: str = "") -> int:
        duration = max((t.end_ms for t in result.trace), default=0.0)
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO reviews (repo, pr_number, title, commit_sha, verdict, files_reviewed, lines_added,
                   finding_count, model, input_tokens, output_tokens, duration_ms, result_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (repo, pr_number, title, commit_sha, result.verdict, result.files_reviewed, result.lines_added,
                 len(result.findings), result.model, result.usage.input_tokens, result.usage.output_tokens,
                 duration, json.dumps(result.to_dict()), time.time()),
            )
            return int(cur.lastrowid)

    def list(self, limit: int = 50, repo: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT id, repo, pr_number, title, verdict, files_reviewed, lines_added, finding_count, model, " \
            "input_tokens, output_tokens, duration_ms, created_at FROM reviews"
        args: list[Any] = []
        if repo:
            q += " WHERE repo = ?"
            args.append(repo)
        q += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [dict(r) for r in self._conn.execute(q, args)]

    def get(self, review_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        return d

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(finding_count),0) f, COALESCE(AVG(duration_ms),0) d, "
                "COALESCE(SUM(input_tokens+output_tokens),0) t FROM reviews").fetchone()
            rows = self._conn.execute("SELECT result_json FROM reviews ORDER BY id DESC LIMIT 500").fetchall()
        by_cat: dict[str, int] = {}
        by_sev: dict[str, int] = {}
        for r in rows:
            for f in json.loads(r["result_json"])["findings"]:
                by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
                by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        return {"reviews": total["n"], "findings": total["f"], "avg_duration_ms": round(total["d"], 1),
                "tokens": total["t"], "by_category": by_cat, "by_severity": by_sev}

    def close(self) -> None:
        self._conn.close()
