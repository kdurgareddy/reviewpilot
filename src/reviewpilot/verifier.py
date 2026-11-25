"""The critic stage: keeps only findings worth a human's attention.

* drops findings that point at lines the PR didn't add (common LLM hallucination)
* merges duplicates of the same issue reported by more than one source
* applies a confidence threshold and per-file / total caps
* ranks by severity, then confidence
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import FileDiff, Finding


@dataclass
class VerifierConfig:
    min_confidence: float = 0.5
    max_per_file: int = 15
    max_total: int = 50
    line_tolerance: int = 0


def verify(findings: list[Finding], files: list[FileDiff], cfg: VerifierConfig | None = None) -> tuple[list[Finding], int]:
    cfg = cfg or VerifierConfig()
    added = {f.path: set(f.added_lines) for f in files}
    kept: dict[tuple[str, int, str], Finding] = {}
    dropped = 0

    for f in findings:
        lines = added.get(f.file)
        if lines is None:
            dropped += 1
            continue
        if f.line not in lines:
            near = [n for n in lines if abs(n - f.line) <= cfg.line_tolerance]
            if not near:
                dropped += 1
                continue
            f.line = min(near, key=lambda n: abs(n - f.line))
        if f.confidence < cfg.min_confidence:
            dropped += 1
            continue
        k = f.key
        if k in kept:
            dropped += 1
            kept[k] = _merge(kept[k], f)
        else:
            kept[k] = f

    ranked = sorted(kept.values(), key=lambda f: (f.severity.rank, -f.confidence, f.file, f.line))
    per_file: dict[str, int] = {}
    out: list[Finding] = []
    for f in ranked:
        if per_file.get(f.file, 0) >= cfg.max_per_file or len(out) >= cfg.max_total:
            dropped += 1
            continue
        per_file[f.file] = per_file.get(f.file, 0) + 1
        out.append(f)
    return out, dropped


def _merge(a: Finding, b: Finding) -> Finding:
    """Keep the more severe / more confident report; record that two sources agreed."""
    best, other = (a, b) if (a.severity.rank, -a.confidence) <= (b.severity.rank, -b.confidence) else (b, a)
    if best.source != other.source:
        best.source = "static+llm"
        best.confidence = min(0.99, max(best.confidence, other.confidence) + 0.05)
    best.suggestion = best.suggestion or other.suggestion
    return best
