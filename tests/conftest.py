import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("REVIEWPILOT_EAGER_APP", "0")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "REVIEWPILOT_PROVIDER"):
    os.environ.pop(k, None)

SAMPLE = (ROOT / "examples" / "sample.diff").read_text()
CASES = ROOT / "eval" / "cases"


def new_file_diff(path: str, source: str) -> str:
    lines = source.strip("\n").splitlines()
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n" + "\n".join("+" + l for l in lines) + "\n")
