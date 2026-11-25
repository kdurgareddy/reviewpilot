"""Core data types shared by every stage of the review pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Category(str, Enum):
    SECURITY = "security"
    BUG = "bug"
    PERFORMANCE = "performance"
    TESTING = "testing"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3}[self.value]


@dataclass
class Line:
    number: int          # line number in the new file (0 for deleted lines)
    text: str
    kind: str            # "+" added, "-" removed, " " context


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    header: str
    lines: list[Line] = field(default_factory=list)

    @property
    def added(self) -> list[Line]:
        return [ln for ln in self.lines if ln.kind == "+"]


@dataclass
class FileDiff:
    path: str
    old_path: str | None
    status: str                      # added | modified | deleted | renamed
    hunks: list[Hunk] = field(default_factory=list)
    language: str = "text"

    @property
    def added_lines(self) -> dict[int, str]:
        return {ln.number: ln.text for h in self.hunks for ln in h.added}

    @property
    def is_test(self) -> bool:
        p = self.path.lower()
        name = p.rsplit("/", 1)[-1]
        return (
            "/tests/" in f"/{p}" or "/test/" in f"/{p}" or "__tests__" in p
            or name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js", "test.java"))
        )


@dataclass
class Finding:
    file: str
    line: int
    category: Category
    severity: Severity
    title: str
    message: str
    rule_id: str = ""
    suggestion: str | None = None
    confidence: float = 0.7
    source: str = "static"           # static | llm | static+llm
    agent: str = ""
    end_line: int | None = None

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.file, self.line, self.category.value)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        d = dict(d)
        d["category"] = Category(d["category"])
        d["severity"] = Severity(d["severity"])
        return cls(**d)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls


@dataclass
class TraceEvent:
    node: str
    start_ms: float
    end_ms: float
    status: str = "ok"
    detail: str = ""


@dataclass
class ReviewResult:
    findings: list[Finding]
    files_reviewed: int
    lines_added: int
    summary: str
    verdict: str                      # approve | comment | request_changes
    usage: Usage = field(default_factory=Usage)
    trace: list[TraceEvent] = field(default_factory=list)
    dropped: int = 0                  # findings removed by the verifier
    model: str = "offline"

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "files_reviewed": self.files_reviewed,
            "lines_added": self.lines_added,
            "summary": self.summary,
            "verdict": self.verdict,
            "usage": asdict(self.usage),
            "trace": [asdict(t) for t in self.trace],
            "dropped": self.dropped,
            "model": self.model,
        }
