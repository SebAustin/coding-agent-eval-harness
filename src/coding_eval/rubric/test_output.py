from __future__ import annotations

import re

_FAILED_NODE_RE = re.compile(r"(?:FAILED|ERROR)\s+(\S+)")


def _normalize_test_path(path: str) -> str:
    return path.replace("\\", "/").removesuffix(".py")


def target_tests_failed(test_files: list[str], pytest_output: str) -> bool:
    """True when pytest reports FAILED/ERROR on a task's test file."""
    if not test_files or not pytest_output.strip():
        return False
    needles = {_normalize_test_path(path) for path in test_files}
    basenames = {path.rsplit("/", 1)[-1] for path in needles}
    for line in pytest_output.splitlines():
        if "FAILED" not in line and "ERROR" not in line:
            continue
        match = _FAILED_NODE_RE.search(line)
        node = match.group(1) if match else line
        for needle in needles:
            if needle in node or needle.replace("/", ".") in node:
                return True
        for base in basenames:
            if base in node:
                return True
    return False


def pytest_has_syntax_error(pytest_output: str) -> bool:
    return (
        "SyntaxError:" in pytest_output or "Interrupted: 1 error during collection" in pytest_output
    )


__all__ = ["pytest_has_syntax_error", "target_tests_failed"]
