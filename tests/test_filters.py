from __future__ import annotations

from typing import Any

from coding_eval.dataset.filters import (
    filter_failure_reasons,
    has_test_coverage,
    issue_body_sufficient,
    not_merged_after_cutoff,
    passes_all_filters,
    single_file_change,
)


def test_issue_body_sufficient_threshold() -> None:
    issue: dict[str, Any] = {"body": "a" * 99}
    assert issue_body_sufficient(issue) is False
    issue_ok: dict[str, Any] = {"body": "a" * 100}
    assert issue_body_sufficient(issue_ok) is True


def test_not_merged_after_cutoff() -> None:
    pr_old: dict[str, Any] = {"merged_at": "2024-12-31T23:59:59Z"}
    pr_new: dict[str, Any] = {"merged_at": "2025-06-01T00:00:00Z"}
    assert not_merged_after_cutoff(pr_old) is True
    assert not_merged_after_cutoff(pr_new) is False


def test_single_file_change_allows_src_plus_test() -> None:
    pr: dict[str, Any] = {
        "changed_files": ["src/widget.py", "tests/test_widget.py"],
    }
    assert single_file_change(pr) is True
    assert has_test_coverage(pr) is True


def test_single_file_change_ignores_changelog() -> None:
    pr: dict[str, Any] = {
        "changed_files": [
            "CHANGELOG.md",
            "rich/table.py",
            "tests/test_table.py",
        ],
    }
    assert single_file_change(pr) is True


def test_single_file_change_allows_three_substantive_two_src() -> None:
    pr: dict[str, Any] = {
        "changed_files": ["a.py", "b.py", "tests/test_a.py"],
    }
    assert single_file_change(pr) is True


def test_single_file_change_rejects_four_substantive_files() -> None:
    pr: dict[str, Any] = {
        "changed_files": ["a.py", "tests/test_a.py", "b.py", "c.py", "d.py"],
    }
    assert single_file_change(pr) is False


def test_issue_has_bug_label_accepts_bug_title() -> None:
    from coding_eval.dataset.filters import issue_has_bug_label

    issue: dict[str, Any] = {"title": "[BUG] something broke", "labels": []}
    assert issue_has_bug_label(issue) is True


def test_passes_all_filters_requires_every_gate() -> None:
    issue: dict[str, Any] = {"body": "x" * 100, "labels": [{"name": "bug"}]}
    pr: dict[str, Any] = {
        "changed_files": ["tests/test_x.py"],
        "merged_at": "2024-01-01T00:00:00Z",
    }
    assert passes_all_filters(issue, pr) is True
    assert filter_failure_reasons(issue, pr) == []
    pr_too_wide = {
        **pr,
        "changed_files": ["a.py", "tests/test_x.py", "b.py", "c.py", "d.py"],
    }
    assert passes_all_filters(issue, pr_too_wide) is False
