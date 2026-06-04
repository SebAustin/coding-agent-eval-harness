from __future__ import annotations

import re

_PY_FILE_RE = re.compile(r"^\+\+\+ b/(.+\.py)$")
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")


def changed_py_files(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        match = _PY_FILE_RE.match(line)
        if match is not None:
            files.append(match.group(1))
    return files


def added_lines_text(patch: str) -> str:
    added: list[str] = []
    for line in patch.splitlines():
        if _ADDED_LINE_RE.match(line):
            added.append(line[1:])
    return "\n".join(added)


__all__ = ["added_lines_text", "changed_py_files"]
