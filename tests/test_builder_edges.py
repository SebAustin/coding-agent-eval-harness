from __future__ import annotations

from typing import Any

import httpx
import pytest

from coding_eval.dataset.builder import GitHubDatasetBuilder, _split_repo


@pytest.mark.asyncio
async def test_build_task_returns_none_without_base_commit() -> None:
    builder = GitHubDatasetBuilder(github_token="t", repos=["o/r"])
    issue: dict[str, Any] = {"number": 1, "body": "x" * 100}
    pr: dict[str, Any] = {"base_commit": "", "changed_files": ["tests/test_a.py"]}
    assert await builder.build_task("o/r", issue, pr) is None


def test_split_repo_rejects_invalid_slug() -> None:
    with pytest.raises(ValueError, match="Invalid repo slug"):
        _split_repo("invalid")
