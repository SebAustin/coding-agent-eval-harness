from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from git import Repo

from coding_eval.agents.claude_code_agentic import MAX_TURNS, ClaudeCodeAgenticAdapter
from coding_eval.dataset.schema import Task


def _task() -> Task:
    return Task(
        task_id="typer-0822",
        repo="tiangolo/typer",
        base_commit="abc123456789",
        issue_number=822,
        issue_title="Rich markup in Zsh completion help lines",
        issue_body="Help strings include Rich markup like [bold] in shell completion.",
        test_files=["tests/test_completion/test_completion_complete.py"],
    )


def _completion_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    pkg = repo / "typer"
    tests = repo / "tests" / "test_completion"
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "completion.py").write_text(
        'from typer._completion_shared import resolve_help\nLINE = resolve_help("x")\n',
        encoding="utf-8",
    )
    (pkg / "_completion_shared.py").write_text(
        "def resolve_help(text):\n    return text\n",
        encoding="utf-8",
    )
    (tests / "test_completion_complete.py").write_text(
        "from typer import completion\n",
        encoding="utf-8",
    )
    git_repo = Repo.init(repo)
    git_repo.index.add(
        [
            "typer/__init__.py",
            "typer/completion.py",
            "typer/_completion_shared.py",
            "tests/test_completion/test_completion_complete.py",
        ],
    )
    git_repo.index.commit("init")
    return repo


def _text_block(text: str) -> MagicMock:
    return MagicMock(type="text", text=text)


def _tool_block(tool_id: str, name: str, tool_input: dict[str, Any]) -> MagicMock:
    block = MagicMock(type="tool_use", id=tool_id, name=name)
    block.input = tool_input
    return block


def _message(blocks: list[MagicMock]) -> MagicMock:
    return MagicMock(
        content=blocks,
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )


_MULTI_FILE_DIFF = (
    "--- a/typer/_completion_shared.py\n"
    "+++ b/typer/_completion_shared.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def resolve_help(text):\n"
    "-    return text\n"
    '+    return text.replace("[bold]", "")\n'
    "--- a/typer/completion.py\n"
    "+++ b/typer/completion.py\n"
    "@@ -1,2 +1,2 @@\n"
    " from typer._completion_shared import resolve_help\n"
    '-LINE = resolve_help("x")\n'
    '+LINE = resolve_help("[bold]x")\n'
)


@pytest.mark.asyncio
async def test_agentic_explores_then_emits_multi_file_diff(tmp_path: Path) -> None:
    repo = _completion_repo(tmp_path)
    adapter = ClaudeCodeAgenticAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        side_effect=[
            _message([_tool_block("t1", "grep", {"pattern": "resolve_help"})]),
            _message([_tool_block("t2", "read_file", {"path": "typer/completion.py"})]),
            _message([_tool_block("t3", "read_file", {"path": "typer/_completion_shared.py"})]),
            _message([_text_block(_MULTI_FILE_DIFF)]),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    # The fix spans two files the up-front context could not surface; the adapter
    # discovered both via tools and produced an applicable patch — no fake tags.
    assert "typer/_completion_shared.py" in result.patch
    assert "typer/completion.py" in result.patch
    assert "<file_search>" not in result.patch
    assert "<read_files>" not in result.patch
    assert adapter._client.messages.create.await_count == 4


@pytest.mark.asyncio
async def test_agentic_emits_diff_without_tools(tmp_path: Path) -> None:
    repo = _completion_repo(tmp_path)
    adapter = ClaudeCodeAgenticAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=_message([_text_block(_MULTI_FILE_DIFF)]),
    )

    result = await adapter.solve(_task(), str(repo))

    assert "typer/_completion_shared.py" in result.patch
    adapter._client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_agentic_retries_after_apply_failure(tmp_path: Path) -> None:
    repo = _completion_repo(tmp_path)
    bad_diff = (
        "--- a/typer/_completion_shared.py\n"
        "+++ b/typer/_completion_shared.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def resolve_help(text):\n"
        "-    return nonexistent_line\n"
        '+    return text.replace("[bold]", "")\n'
    )
    adapter = ClaudeCodeAgenticAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        side_effect=[
            _message([_text_block(bad_diff)]),
            _message([_text_block(_MULTI_FILE_DIFF)]),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert "typer/completion.py" in result.patch
    assert adapter._client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_agentic_reprompts_when_no_tool_and_no_diff(tmp_path: Path) -> None:
    repo = _completion_repo(tmp_path)
    adapter = ClaudeCodeAgenticAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        side_effect=[
            _message([_text_block("Let me think about this problem.")]),
            _message([_text_block(_MULTI_FILE_DIFF)]),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert "typer/completion.py" in result.patch
    assert adapter._client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_agentic_gives_up_after_max_turns(tmp_path: Path) -> None:
    repo = _completion_repo(tmp_path)
    adapter = ClaudeCodeAgenticAdapter(api_key="test-key")
    adapter._client = AsyncMock()
    adapter._client.messages.create = AsyncMock(
        return_value=_message([_text_block("Still thinking, no diff yet.")]),
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == ""
    assert adapter._client.messages.create.await_count == MAX_TURNS
