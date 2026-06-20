"""Claude cost-accumulation lock test.

Added in M2 to guard the refactor seam: the solver now owns cost accumulation
(incremental per-call costs summed), whereas the old _append_completion returned
cumulative totals. This test pins the final cost_usd for the Claude single-shot
happy path so a cost-accumulation bug cannot pass the existing 173-test suite
silently (see PLAN.md §7, R1 coverage map).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from git import Repo

from coding_eval.agents._common import INPUT_USD_PER_MTOK, OUTPUT_USD_PER_MTOK
from coding_eval.agents.claude_code import ClaudeCodeAdapter
from coding_eval.dataset.schema import Task


def _task() -> Task:
    return Task(
        task_id="t_cost",
        repo="Textualize/rich",
        base_commit="abc123456789",
        issue_number=1,
        issue_title="Fix bug",
        issue_body="Something broke in rich/pretty.py",
        test_files=["tests/test_pretty.py"],
    )


def _make_repo(tmp_path: Path) -> Path:
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
async def test_claude_cost_single_call(tmp_path: Path) -> None:
    """Single happy-path call: cost_usd == (prompt * INPUT + completion * OUTPUT) / 1e6 exactly."""
    repo = _make_repo(tmp_path)
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    prompt_tokens = 100
    completion_tokens = 50

    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text=good_patch)],
            usage=MagicMock(input_tokens=prompt_tokens, output_tokens=completion_tokens),
        ),
    )

    result = await adapter.solve(_task(), str(repo))

    expected_cost = (
        prompt_tokens * INPUT_USD_PER_MTOK + completion_tokens * OUTPUT_USD_PER_MTOK
    ) / 1_000_000
    assert result.patch == good_patch
    assert result.cost_usd == pytest.approx(expected_cost)
