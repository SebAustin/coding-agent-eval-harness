from __future__ import annotations

import re

_PY_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+\.py)$")
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")


def changed_py_files(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        match = _PY_FILE_RE.match(line)
        if match is not None:
            path = match.group(1).strip()
            if path != "/dev/null" and path not in files:
                files.append(path)
    return files


def is_test_file_path(path: str) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    if norm.startswith("tests/") or "/tests/" in norm:
        return True
    name = norm.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def patch_only_modifies_tests(patch: str) -> bool:
    files = changed_py_files(patch)
    if not files:
        return False
    return all(is_test_file_path(path) for path in files)


def added_lines_text(patch: str) -> str:
    added: list[str] = []
    for line in patch.splitlines():
        if _ADDED_LINE_RE.match(line):
            added.append(line[1:])
    return "\n".join(added)


__all__ = [
    "added_lines_text",
    "changed_py_files",
    "is_test_file_path",
    "patch_only_modifies_tests",
]
