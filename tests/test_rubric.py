from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch as mock_patch

import pytest
from git import Repo

from coding_eval.rubric import complexity, diff_minimality, semantic, style, test_pass
from coding_eval.rubric._patch_files import added_lines_text, changed_py_files
from coding_eval.rubric.scorer import WEIGHTS, RubricScores, score
from coding_eval.sandbox.runner import SandboxResult


def _sandbox(stdout: str, *, exit_code: int = 0, timed_out: bool = False) -> SandboxResult:
    return SandboxResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_ms=1.0,
        timed_out=timed_out,
    )


def test_diff_minimality_small_patch() -> None:
    patch = "".join(f"+line {i}\n" for i in range(5))
    patch += "".join(f"-old {i}\n" for i in range(5))
    assert diff_minimality.score(patch) > 0.90


def test_diff_minimality_large_patch_scores_zero() -> None:
    patch = "".join(f"+line {i}\n" for i in range(250))
    assert diff_minimality.score(patch) == 0.0


def test_diff_minimality_ignores_headers() -> None:
    patch = "--- a/x.py\n+++ b/x.py\n+only\n"
    assert diff_minimality.score(patch) == 1.0 - 1 / diff_minimality.MAX_REASONABLE_LINES


def test_test_pass_success() -> None:
    result = _sandbox("3 passed in 0.1s")
    assert test_pass.score(result) == 1.0


def test_test_pass_timeout_or_error() -> None:
    assert test_pass.score(_sandbox("", exit_code=1)) == 0.0
    assert test_pass.score(_sandbox("1 passed", timed_out=True)) == 0.0
    assert test_pass.score(_sandbox("no tests ran", exit_code=0)) == 0.0


def test_patch_files_helpers() -> None:
    patch = "--- a/foo.py\n+++ b/foo.py\n+added\n-old\n"
    assert changed_py_files(patch) == ["foo.py"]
    assert added_lines_text(patch) == "added"


def test_style_score_clean_and_e501(tmp_path: Path) -> None:
    clean_patch = (
        "--- a/x.py\n+++ b/x.py\n"
        "+def ok() -> None:\n"
        "+    return None\n"
    )
    assert style.score(clean_patch, str(tmp_path)) == 1.0

    padding = "a" * 96
    bad_patch = f"--- a/x.py\n+++ b/x.py\n+    value = '{padding}'\n"
    bad_score = style.score(bad_patch, str(tmp_path))
    assert bad_score < 1.0


def test_style_empty_added_lines() -> None:
    assert style.score("--- a/x\n+++ b/x\n", "/tmp") == 1.0


def test_complexity_no_python_files() -> None:
    assert complexity.score("--- a/readme.md\n+++ b/readme.md\n", "/tmp") == 1.0


def test_complexity_with_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    mod = repo / "mod.py"
    mod.write_text("def f():\n    return 1\n", encoding="utf-8")
    git_repo = Repo.init(repo)
    git_repo.index.add(["mod.py"])
    git_repo.index.commit("init")
    original = mod.read_text(encoding="utf-8")
    mod.write_text("def f():\n    if True:\n        return 2\n    return 1\n", encoding="utf-8")
    patch = git_repo.git.diff("HEAD")
    mod.write_text(original, encoding="utf-8")
    if not patch.endswith("\n"):
        patch += "\n"
    value = complexity.score(patch, str(repo))
    assert 0.0 <= value <= 1.0


def test_complexity_apply_failure(tmp_path: Path) -> None:
    from coding_eval.patching.git_apply import PatchApplyError

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("x = 1\n", encoding="utf-8")
    bad_patch = "--- a/mod.py\n+++ b/mod.py\n@@ -1 +1,2 @@\n-x = 1\n+x = 1\n+broken\n"
    with mock_patch(
        "coding_eval.rubric.complexity.apply_unified_diff",
        side_effect=PatchApplyError("apply failed"),
    ):
        assert complexity.score(bad_patch, str(repo)) == 0.0


def test_semantic_parse_and_clamp() -> None:
    assert semantic._parse_score_from_text('{"score": 0.85, "reasoning": "ok"}') == 0.85
    assert semantic._parse_score_from_text('{"score": 2.0, "reasoning": "high"}') == 1.0
    assert semantic._parse_score_from_text("not json") == 0.0
    assert (
        semantic._parse_score_from_text('text {"score": 0.4, "reasoning": "x"} tail')
        == 0.4
    )


@pytest.mark.asyncio
async def test_semantic_score_mocked(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite"
    client = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text='{"score": 0.85, "reasoning": "good"}')],
        ),
    )
    value = await semantic.score("issue body", "patch text", client, cache_path=cache_path)
    assert value == 0.85
    client.messages.create.assert_awaited_once()

    cached = await semantic.score("issue body", "patch text", client, cache_path=cache_path)
    assert cached == 0.85
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_semantic_cache_read_write(tmp_path: Path) -> None:
    cache_path = tmp_path / "semantic.sqlite"
    key = semantic._cache_key("issue", "patch")
    semantic._write_cache(cache_path, key, 0.42)
    assert semantic._read_cache(cache_path, key) == 0.42
    assert semantic._read_cache(cache_path, "missing") is None


def test_semantic_message_text() -> None:
    message = MagicMock(
        content=[
            MagicMock(type="text", text="hello"),
            MagicMock(type="tool_use", text="ignored"),
        ],
    )
    assert semantic._message_text(message) == "hello"


def test_composite_weighted_sum() -> None:
    s = RubricScores(
        test_pass_rate=1.0,
        diff_minimality=0.5,
        complexity_delta=0.5,
        style_score=0.5,
        semantic_score=0.5,
    )
    expected = sum(getattr(s, k) * v for k, v in WEIGHTS.items())
    assert abs(s.composite - expected) < 1e-9


@pytest.mark.asyncio
async def test_scorer_orchestrator(tmp_path: Path) -> None:
    cache_path = tmp_path / "sem.sqlite"
    client = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text=json.dumps({"score": 0.8, "reasoning": "x"}))],
        ),
    )
    sandbox = _sandbox("2 passed in 0.2s")
    diff_patch = "--- a/a.py\n+++ b/a.py\n+print('hi')\n"

    with (
        mock_patch("coding_eval.rubric.scorer.test_pass.score", return_value=1.0),
        mock_patch("coding_eval.rubric.scorer.diff_minimality.score", return_value=0.9),
        mock_patch("coding_eval.rubric.scorer.complexity.score", return_value=0.8),
        mock_patch("coding_eval.rubric.scorer.style.score", return_value=0.7),
    ):
        result = await score(
            "issue",
            diff_patch,
            sandbox,
            str(tmp_path),
            client,
            semantic_cache_path=str(cache_path),
        )

    assert result.test_pass_rate == 1.0
    assert result.diff_minimality == 0.9
    assert result.complexity_delta == 0.8
    assert result.style_score == 0.7
    assert result.semantic_score == 0.8


def test_complexity_high_delta_scores_low(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    mod = repo / "mod.py"
    mod.write_text("def f():\n    return 1\n", encoding="utf-8")
    with (
        mock_patch("coding_eval.rubric.complexity.apply_unified_diff"),
        mock_patch(
            "coding_eval.rubric.complexity._mean_complexity",
            side_effect=[1.0, 15.0],
        ),
    ):
        value = complexity.score("--- a/mod.py\n+++ b/mod.py\n+pass\n", str(repo))
    assert value == 0.0


def test_complexity_missing_file_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    patch = "--- a/missing.py\n+++ b/missing.py\n+pass\n"
    with mock_patch("coding_eval.rubric.complexity.apply_unified_diff"):
        value = complexity.score(patch, str(repo))
    assert value == 1.0


def test_semantic_ensure_cache_table(tmp_path: Path) -> None:
    cache_path = tmp_path / "new.sqlite"
    import sqlite3

    with sqlite3.connect(cache_path) as conn:
        semantic._ensure_cache_table(conn)
    assert cache_path.exists()
