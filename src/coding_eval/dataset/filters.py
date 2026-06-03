from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

MERGE_CUTOFF = datetime(2025, 1, 1, tzinfo=UTC)
MIN_ISSUE_BODY_LEN = 100
BUG_LABEL_NAMES = frozenset({"bug", "type: bug", "type:bug", "kind/bug"})
MAX_SUBSTANTIVE_FILES = 3
MAX_NON_TEST_FILES = 2
IGNORED_BASENAMES = frozenset(
    {
        "CHANGELOG.md",
        "CHANGES.md",
        "CONTRIBUTORS.md",
        "LICENSE",
        "LICENSE.md",
        "README.md",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        ".pre-commit-config.yaml",
    },
)
IGNORED_PREFIXES = (
    "docs/",
    ".github/",
    "examples/",
    "changelog/",
)


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _is_ignorable_path(path: str) -> bool:
    norm = _normalize_path(path)
    parts = norm.split("/")
    filename = parts[-1]
    if filename in IGNORED_BASENAMES:
        return True
    if any(norm.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return True
    if filename.endswith(".md") and "/tests/" not in norm and "/test/" not in norm:
        return True
    if filename.endswith((".png", ".svg", ".jpg", ".jpeg", ".gif", ".ico")):
        return True
    return False


def substantive_changed_files(pr: dict[str, Any]) -> list[str]:
    changed = pr.get("changed_files", [])
    if not isinstance(changed, list):
        return []
    return [
        _normalize_path(name)
        for name in changed
        if isinstance(name, str) and not _is_ignorable_path(name)
    ]


def _is_test_file(path: str) -> bool:
    parts = _normalize_path(path).split("/")
    filename = parts[-1]
    return filename.startswith("test_") and filename.endswith(".py")


def single_file_change(pr: dict[str, Any]) -> bool:
    """Bounded scope: ≤3 substantive files, ≥1 test_*.py, ≤2 non-test files."""
    substantive = substantive_changed_files(pr)
    if not substantive or len(substantive) > MAX_SUBSTANTIVE_FILES:
        return False
    test_paths = [name for name in substantive if _is_test_file(name)]
    non_test_paths = [name for name in substantive if not _is_test_file(name)]
    if not test_paths:
        return False
    return len(non_test_paths) <= MAX_NON_TEST_FILES


def has_test_coverage(pr: dict[str, Any]) -> bool:
    changed = pr.get("changed_files", [])
    if not isinstance(changed, list):
        return False
    return any(
        isinstance(name, str) and _is_test_file(_normalize_path(name))
        for name in changed
    )


def _label_name_is_bug(name: str) -> bool:
    lower = name.strip().lower()
    if lower in BUG_LABEL_NAMES:
        return True
    return "bug" in lower.replace(":", " ").replace("/", " ").split()


def issue_has_bug_label(issue: dict[str, Any]) -> bool:
    if issue.get("_bug_query_match") is True:
        return True
    title = str(issue.get("title") or "").lower()
    if "[bug]" in title:
        return True
    labels = issue.get("labels", [])
    if not isinstance(labels, list):
        return False
    return any(
        isinstance(label, dict)
        and _label_name_is_bug(str(label.get("name", "")))
        for label in labels
    )


def issue_body_sufficient(issue: dict[str, Any]) -> bool:
    body = issue.get("body") or ""
    if not isinstance(body, str):
        return False
    return len(body.strip()) >= MIN_ISSUE_BODY_LEN


def not_merged_after_cutoff(pr: dict[str, Any]) -> bool:
    merged_at = _parse_github_datetime(pr.get("merged_at"))
    if merged_at is None:
        return False
    return merged_at < MERGE_CUTOFF


def filter_failure_reasons(issue: dict[str, Any], pr: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not single_file_change(pr):
        substantive = substantive_changed_files(pr)
        n = len(substantive)
        reasons.append(f"scope(nsubstantive={n})")
    if not has_test_coverage(pr):
        reasons.append("no_test")
    if not issue_has_bug_label(issue):
        reasons.append("no_bug_label")
    if not issue_body_sufficient(issue):
        reasons.append("short_body")
    if not not_merged_after_cutoff(pr):
        reasons.append("merged_after_cutoff")
    return reasons


def passes_all_filters(issue: dict[str, Any], pr: dict[str, Any]) -> bool:
    return not filter_failure_reasons(issue, pr)


__all__ = [
    "BUG_LABEL_NAMES",
    "MERGE_CUTOFF",
    "MIN_ISSUE_BODY_LEN",
    "filter_failure_reasons",
    "has_test_coverage",
    "issue_has_bug_label",
    "issue_body_sufficient",
    "not_merged_after_cutoff",
    "passes_all_filters",
    "single_file_change",
    "substantive_changed_files",
]
