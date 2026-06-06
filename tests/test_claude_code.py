from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from git import Repo

from coding_eval.agents.claude_code import ClaudeCodeAdapter
from coding_eval.dataset.schema import Task


def _task() -> Task:
    return Task(
        task_id="t1",
        repo="Textualize/rich",
        base_commit="abc123456789",
        issue_number=1,
        issue_title="Fix bug",
        issue_body="Something broke in rich/pretty.py",
        test_files=["tests/test_pretty.py"],
    )


@pytest.mark.asyncio
async def test_claude_retry_on_apply_check_failure(tmp_path: Path) -> None:
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

    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = ClaudeCodeAdapter(api_key="test-key")
    first = MagicMock(
        content=[MagicMock(type="text", text=bad_patch)],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    second = MagicMock(
        content=[MagicMock(type="text", text=good_patch)],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(side_effect=[first, second])

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    assert adapter._client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_claude_no_retry_when_patch_applies(tmp_path: Path) -> None:
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

    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text=good_patch)],
            usage=MagicMock(input_tokens=100, output_tokens=50),
        ),
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    adapter._client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_claude_rejects_retry_patch_that_fails_apply_check(tmp_path: Path) -> None:
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

    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    still_bad_patch = (
        "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-wrong\n+value = 2\n"
    )
    third_bad_patch = (
        "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-nope\n+value = 2\n"
    )

    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        side_effect=[
            MagicMock(
                content=[MagicMock(type="text", text=bad_patch)],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            ),
            MagicMock(
                content=[MagicMock(type="text", text=still_bad_patch)],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            ),
            MagicMock(
                content=[MagicMock(type="text", text=third_bad_patch)],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            ),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == ""
    assert adapter._client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_claude_rejects_patch_with_syntax_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    tests = repo / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "pretty.py").write_text("while True:\n    pass\n", encoding="utf-8")
    (tests / "test_pretty.py").write_text("from rich import pretty\n", encoding="utf-8")
    git_repo = Repo.init(repo)
    git_repo.index.add(["rich/__init__.py", "rich/pretty.py", "tests/test_pretty.py"])
    git_repo.index.commit("init")

    syntax_patch = (
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1,2 +1,3 @@\n"
        " while True:\n"
        "+    raise (\n"
        "     pass\n"
    )

    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(type="text", text=syntax_patch)],
            usage=MagicMock(input_tokens=100, output_tokens=50),
        ),
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == ""
    assert adapter._client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_claude_format_reprompt_when_extract_empty(tmp_path: Path) -> None:
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

    malformed = (
        "The fix removes the early return.\n\n"
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1 +1 @@\n"
        "broken-line-without-prefix\n"
    )
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = ClaudeCodeAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        side_effect=[
            MagicMock(
                content=[MagicMock(type="text", text=malformed)],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            ),
            MagicMock(
                content=[MagicMock(type="text", text=good_patch)],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            ),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    assert adapter._client.messages.create.await_count == 2
    assert "--- format fixup ---" in result.raw_response
