"""Parse unified diffs (``git diff`` / GitHub ``.diff`` format) into structured hunks.

Every added line keeps its line number in the *new* file, which is what GitHub
needs to anchor an inline review comment.
"""

from __future__ import annotations

import re

from .models import FileDiff, Hunk, Line

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".go": "go",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".kt": "kotlin", ".rs": "rust",
    ".sql": "sql", ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".sh": "shell",
}


def detect_language(path: str) -> str:
    for ext, lang in LANGUAGES.items():
        if path.endswith(ext):
            return lang
    return "text"


def _strip_prefix(p: str) -> str | None:
    p = p.strip().split("\t")[0]
    if p == "/dev/null":
        return None
    return p[2:] if p[:2] in ("a/", "b/") else p


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    hunk: Hunk | None = None
    new_no = 0
    remaining_old = remaining_new = 0   # lines left in the current hunk

    for raw in text.splitlines():
        in_hunk = hunk is not None and (remaining_old > 0 or remaining_new > 0)

        if not in_hunk:
            if raw.startswith("diff --git "):
                m = re.match(r"diff --git a/(.+?) b/(.+)$", raw)
                path = m.group(2) if m else raw.split()[-1]
                cur = FileDiff(path=path, old_path=m.group(1) if m else path,
                               status="modified", language=detect_language(path))
                files.append(cur)
                hunk = None
                continue
            if raw.startswith("--- "):
                if cur is None or cur.hunks:
                    cur = FileDiff(path="", old_path=None, status="modified")
                    files.append(cur)
                cur.old_path = _strip_prefix(raw[4:])
                continue
            if raw.startswith("+++ ") and cur is not None:
                new = _strip_prefix(raw[4:])
                if new is None:
                    cur.status = "deleted"
                else:
                    cur.path, cur.language = new, detect_language(new)
                    if cur.old_path is None:
                        cur.status = "added"
                continue
            if cur is not None:
                if raw.startswith("new file mode"):
                    cur.status = "added"
                    continue
                if raw.startswith("deleted file mode"):
                    cur.status = "deleted"
                    continue
                if raw.startswith("rename from "):
                    cur.status, cur.old_path = "renamed", raw[len("rename from "):]
                    continue
                if raw.startswith("rename to "):
                    cur.path = raw[len("rename to "):]
                    cur.language = detect_language(cur.path)
                    continue
            m = _HUNK.match(raw)
            if m and cur is not None:
                old_len = int(m.group(2)) if m.group(2) is not None else 1
                new_len = int(m.group(4)) if m.group(4) is not None else 1
                new_no = int(m.group(3))
                remaining_old, remaining_new = old_len, new_len
                hunk = Hunk(int(m.group(1)), old_len, new_no, new_len, m.group(5).strip())
                cur.hunks.append(hunk)
            continue

        # inside a hunk
        tag, body = (raw[0], raw[1:]) if raw else (" ", "")
        if tag == "\\":            # "\ No newline at end of file"
            continue
        if tag == "+":
            hunk.lines.append(Line(new_no, body, "+"))
            new_no += 1
            remaining_new -= 1
        elif tag == "-":
            hunk.lines.append(Line(0, body, "-"))
            remaining_old -= 1
        else:
            hunk.lines.append(Line(new_no, body, " "))
            new_no += 1
            remaining_old -= 1
            remaining_new -= 1

    return [f for f in files if f.path and f.status != "deleted"]


def render_numbered(fd: FileDiff, max_lines: int = 400) -> str:
    """Render a file's hunks with new-file line numbers, for LLM prompts."""
    out = [f"File: {fd.path} ({fd.language}, {fd.status})"]
    count = 0
    for h in fd.hunks:
        out.append(f"@@ {h.header}".rstrip())
        for ln in h.lines:
            if count >= max_lines:
                out.append("... (truncated)")
                return "\n".join(out)
            num = f"{ln.number:>5}" if ln.kind != "-" else "     "
            out.append(f"{num} {ln.kind} {ln.text}")
            count += 1
    return "\n".join(out)
