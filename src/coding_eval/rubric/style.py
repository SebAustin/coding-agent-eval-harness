from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from coding_eval.rubric._patch_files import added_lines_text

_RUFF_IGNORE = "D,ANN101,COM812,ISC001,INP001"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_VIOLATION_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?P<col>\d+): (?P<code>\w+)\d* ",
)


def _count_ruff_violations(source: str) -> int:
    if not source.strip():
        return 0
    if not source.endswith("\n"):
        source = f"{source}\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        delete=False,
    ) as tmp:
        tmp.write(source)
        tmp_path = tmp.name

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select=ALL",
                "--ignore",
                _RUFF_IGNORE,
                tmp_path,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    output = _ANSI_RE.sub("", f"{completed.stdout}\n{completed.stderr}")
    return sum(1 for line in output.splitlines() if _VIOLATION_RE.match(line))


def score(patch: str, repo_path: str) -> float:
    _ = repo_path
    added = added_lines_text(patch)
    violations = _count_ruff_violations(added)
    return max(0.0, 1.0 - violations / 20.0)


__all__ = ["score"]
