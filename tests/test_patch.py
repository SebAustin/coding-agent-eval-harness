from __future__ import annotations

import pytest

from coding_eval.sandbox.patch import compute_test_pass_rate, parse_test_results
from coding_eval.sandbox.runner import SandboxResult


def test_parse_test_results_passed_with_warning() -> None:
    stdout = "3 passed, 1 warning in 0.12s"
    assert parse_test_results(stdout) == (3, 3)


def test_parse_test_results_failed_and_passed() -> None:
    stdout = "2 failed, 1 passed in 0.42s"
    assert parse_test_results(stdout) == (1, 3)


def test_compute_test_pass_rate_from_sandbox_result() -> None:
    result = SandboxResult(
        exit_code=0,
        stdout="2 passed in 0.05s",
        stderr="",
        duration_ms=50.0,
        timed_out=False,
    )
    assert compute_test_pass_rate(result) == 1.0


def test_compute_test_pass_rate_partial_failure() -> None:
    result = SandboxResult(
        exit_code=1,
        stdout="43 passed, 1 failed in 0.28s",
        stderr="",
        duration_ms=280.0,
        timed_out=False,
    )
    assert compute_test_pass_rate(result) == pytest.approx(43 / 44)


def test_compute_test_pass_rate_zeros_when_task_test_failed() -> None:
    result = SandboxResult(
        exit_code=1,
        stdout=(
            "FAILED tests/test_pretty.py::test_attrs_broken - AssertionError\n"
            "43 passed, 1 failed in 0.28s"
        ),
        stderr="",
        duration_ms=280.0,
        timed_out=False,
    )
    assert compute_test_pass_rate(result, test_files=["tests/test_pretty.py"]) == 0.0
    assert compute_test_pass_rate(result) == pytest.approx(43 / 44)


def test_parse_test_results_empty() -> None:
    assert parse_test_results("") == (0, 0)
