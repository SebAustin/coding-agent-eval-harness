from __future__ import annotations

import re

from coding_eval.sandbox.runner import SandboxResult

_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERROR_RE = re.compile(r"(\d+)\s+error")


def parse_test_results(pytest_stdout: str) -> tuple[int, int]:
    """Parse pytest -q summary lines; returns (passed, total)."""
    passed_m = _PASSED_RE.search(pytest_stdout)
    failed_m = _FAILED_RE.search(pytest_stdout)
    error_m = _ERROR_RE.search(pytest_stdout)
    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    errors = int(error_m.group(1)) if error_m else 0
    total = passed + failed + errors
    if total == 0 and passed > 0:
        return passed, passed
    return passed, total


def compute_test_pass_rate(
    sandbox_result: SandboxResult,
    *,
    test_files: list[str] | None = None,
) -> float:
    output = f"{sandbox_result.stdout}\n{sandbox_result.stderr}"
    if test_files:
        from coding_eval.rubric.test_output import target_tests_failed

        if target_tests_failed(test_files, output):
            return 0.0
    passed, total = parse_test_results(sandbox_result.stdout)
    if total == 0:
        return 0.0
    return passed / total


__all__ = ["compute_test_pass_rate", "parse_test_results"]
