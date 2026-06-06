from __future__ import annotations

from coding_eval.sandbox.patch import compute_test_pass_rate
from coding_eval.sandbox.runner import SandboxResult


def score(sandbox_result: SandboxResult) -> float:
    if sandbox_result.timed_out:
        return 0.0
    return compute_test_pass_rate(sandbox_result)


__all__ = ["score"]
