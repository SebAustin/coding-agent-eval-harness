"""Tests for the diff-path escape guard (SECURITY.md M-2).

Two levels:
1. Pure-function tests of ``patch_paths_within_repo`` (fast, filesystem-light).
2. An integration test through the shared solver with a mocked client, proving the
   guard rejects an escaping patch even when git/compile validation is stubbed to pass.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import coding_eval.agents._solver as solver_mod
from coding_eval.agents.claude_code import ClaudeCodeAdapter
from coding_eval.dataset.schema import Task
from coding_eval.patching.validate import patch_paths_within_repo


def _patch(target: str, *, source: str | None = None) -> str:
    src = source if source is not None else target
    return f"--- a/{src}\n+++ b/{target}\n@@ -1 +1 @@\n-old\n+new\n"


# ---------------------------------------------------------------------------
# Pure-function tests: patch_paths_within_repo
# ---------------------------------------------------------------------------


def test_normal_in_repo_path_passes(tmp_path: Path) -> None:
    ok, error = patch_paths_within_repo(str(tmp_path), _patch("pkg/mod.py"))
    assert ok is True
    assert error == ""


def test_deeply_nested_in_repo_path_passes(tmp_path: Path) -> None:
    ok, error = patch_paths_within_repo(str(tmp_path), _patch("a/b/c/d/e/mod.py"))
    assert ok is True
    assert error == ""


def test_parent_traversal_rejected(tmp_path: Path) -> None:
    ok, error = patch_paths_within_repo(str(tmp_path), _patch("../../etc/passwd"))
    assert ok is False
    assert "escapes repo root" in error


def test_absolute_posix_path_rejected(tmp_path: Path) -> None:
    ok, error = patch_paths_within_repo(str(tmp_path), _patch("/etc/passwd"))
    assert ok is False
    assert "escapes repo root" in error


def test_windows_drive_path_rejected(tmp_path: Path) -> None:
    ok, error = patch_paths_within_repo(str(tmp_path), _patch("C:/Windows/System32/x"))
    assert ok is False
    assert "escapes repo root" in error


def test_backslash_traversal_rejected(tmp_path: Path) -> None:
    # Backslashes are normalized to forward slashes before the containment check.
    ok, _ = patch_paths_within_repo(str(tmp_path), _patch("..\\..\\secret.txt"))
    assert ok is False


def test_source_side_traversal_rejected(tmp_path: Path) -> None:
    # An escape on the `---` (source) header is caught too, not only `+++`.
    patch = "--- a/../../etc/passwd\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-old\n+new\n"
    ok, error = patch_paths_within_repo(str(tmp_path), patch)
    assert ok is False
    assert "escapes repo root" in error


def test_dev_null_new_file_passes(tmp_path: Path) -> None:
    # New file: `--- /dev/null` is the sentinel and must not be treated as an escape.
    patch = "--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1 @@\n+value = 1\n"
    ok, error = patch_paths_within_repo(str(tmp_path), patch)
    assert ok is True
    assert error == ""


def test_in_repo_dotdot_that_does_not_escape_passes(tmp_path: Path) -> None:
    # `..` that resolves back inside the repo is allowed — the guard rejects escapes,
    # not every literal `..`.
    ok, error = patch_paths_within_repo(str(tmp_path), _patch("pkg/sub/../mod.py"))
    assert ok is True
    assert error == ""


def test_empty_patch_passes(tmp_path: Path) -> None:
    ok, error = patch_paths_within_repo(str(tmp_path), "")
    assert ok is True
    assert error == ""


# ---------------------------------------------------------------------------
# Integration: the guard rejects through the solver even if git/compile would pass
# ---------------------------------------------------------------------------


def _task() -> Task:
    return Task(
        task_id="t1",
        repo="Textualize/rich",
        base_commit="abc123456789",
        issue_number=1,
        issue_title="Fix bug",
        issue_body="Something broke",
        test_files=["tests/test_pretty.py"],
    )


def _make_repo(tmp_path: Path) -> Path:
    from git import Repo

    repo = tmp_path / "repo"
    pkg = repo / "rich"
    tests = repo / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "pretty.py").write_text("value = 1\n", encoding="utf-8")
    (tests / "test_pretty.py").write_text("from rich import pretty\n", encoding="utf-8")
    git_repo = Repo.init(repo)
    git_repo.index.add(["rich/__init__.py", "rich/pretty.py", "tests/test_pretty.py"])
    git_repo.index.commit("init")
    return repo


@pytest.mark.asyncio
async def test_solver_path_guard_rejects_escaping_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    # Stub git-apply check and py-compile to ALWAYS pass, so the path guard is the only
    # thing that can reject the patch. If it rejects, the run ends with an empty patch.
    monkeypatch.setattr(solver_mod, "check_unified_diff", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(solver_mod, "patch_py_files_compile", lambda *_a, **_k: (True, ""))

    escaping = _patch("../../../../etc/passwd")
    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text=escaping)],
            usage=MagicMock(input_tokens=10, output_tokens=5),
        ),
    )

    result = await adapter.solve(_task(), str(repo))

    # Guard rejected it on every attempt despite git/compile being stubbed to pass.
    assert result.patch == ""


@pytest.mark.asyncio
async def test_solver_accepts_in_repo_patch_with_guard_active(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text=good_patch)],
            usage=MagicMock(input_tokens=10, output_tokens=5),
        ),
    )

    result = await adapter.solve(_task(), str(repo))

    # A normal in-repo patch is unaffected by the guard and applies on the first try.
    assert result.patch == good_patch
