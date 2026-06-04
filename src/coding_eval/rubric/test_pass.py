from __future__ import annotations

from coding_eval.sandbox.patch import parse_test_results
from coding_eval.sandbox.runner import SandboxResult


def score(sandbox_result: SandboxResult) -> float:
    if sandbox_result.timed_out or sandbox_result.exit_code != 0:
        return 0.0
    passed, total = parse_test_results(sandbox_result.stdout)
    if total == 0:
        return 0.0
    return passed / total


__all__ = ["score"]
