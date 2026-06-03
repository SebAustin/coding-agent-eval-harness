from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from coding_eval.dataset.builder import GitHubDatasetBuilder
from coding_eval.dataset.filters import (
    has_test_coverage,
    passes_all_filters,
    single_file_change,
)
from coding_eval.dataset.io import load_tasks
from coding_eval.dataset.schema import Task

API = "https://api.github.com"


def _make_builder(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> GitHubDatasetBuilder:
    transport = httpx.MockTransport(handler)

    def _client(_self: GitHubDatasetBuilder) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            base_url=API,
            headers=_self._headers,
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        )

    b = GitHubDatasetBuilder(github_token="test-token", repos=["o/r"])
    monkeypatch.setattr(GitHubDatasetBuilder, "_client", _client)
    return b


def _default_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/repos/o/r/issues/42/timeline":
        return httpx.Response(200, json=[])
    if path == "/repos/o/r/issues":
        return httpx.Response(
            200,
            json=[
                {
                    "number": 1,
                    "title": "real issue",
                    "body": "body",
                    "pull_request": None,
                },
                {
                    "number": 2,
                    "title": "actually a pr",
                    "body": "body",
                    "pull_request": {"url": "https://api.github.com/pulls/2"},
                },
            ],
        )
    if path == "/search/issues":
        return httpx.Response(
            200,
            json={
                "items": [
                    {"number": 99, "title": "Fix widget", "body": "fixes #42"},
                ],
            },
        )
    if path == "/repos/o/r/pulls/99":
        return httpx.Response(
            200,
            json={
                "merged_at": "2024-06-01T00:00:00Z",
                "base": {"sha": "deadbeef"},
            },
        )
    if path == "/repos/o/r/pulls/99/files":
        return httpx.Response(200, json=[{"filename": "tests/test_widget.py"}])
    if path == "/repos/o/r/issues/42/comments":
        return httpx.Response(
            200,
            json=[
                {
                    "body": "Try patching the serializer first.",
                    "reactions": {"+1": 12},
                },
            ],
        )
    return httpx.Response(404, json={"message": "not mocked"})


def _run_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/search/issues":
        query = request.url.params.get("q", "")
        if "closes:7" in query:
            return httpx.Response(
                200,
                json={"items": [{"number": 8, "title": "Fix", "body": "fixes #7"}]},
            )
        return httpx.Response(200, json={"items": []})
    if path.endswith("/timeline"):
        return httpx.Response(200, json=[])
    if path == "/repos/o/r/issues":
        return httpx.Response(
            200,
            json=[
                {
                    "number": 7,
                    "title": "Bug",
                    "body": "y" * 100,
                    "pull_request": None,
                    "labels": [{"name": "bug"}],
                },
            ],
        )
    if path == "/repos/o/r/pulls/8":
        return httpx.Response(
            200,
            json={
                "merged_at": "2024-01-01T00:00:00Z",
                "base": {"sha": "cafebabe"},
            },
        )
    if path == "/repos/o/r/pulls/8/files":
        return httpx.Response(200, json=[{"filename": "tests/test_run.py"}])
    if path == "/repos/o/r/issues/7":
        return httpx.Response(
            200,
            json={
                "number": 7,
                "title": "Bug",
                "body": "y" * 100,
                "labels": [{"name": "bug"}],
            },
        )
    if path == "/repos/o/r/issues/7/comments":
        return httpx.Response(200, json=[])
    if path.endswith("/pulls"):
        return httpx.Response(200, json=[])
    return httpx.Response(404, json={"message": "not mocked"})


@pytest.fixture
def builder(monkeypatch: pytest.MonkeyPatch) -> GitHubDatasetBuilder:
    return _make_builder(monkeypatch, _default_handler)


@pytest.fixture
def builder_run(monkeypatch: pytest.MonkeyPatch) -> GitHubDatasetBuilder:
    return _make_builder(monkeypatch, _run_handler)


def test_load_10_tasks_and_required_fields(fixtures_dir: Path) -> None:
    tasks = load_tasks(fixtures_dir / "tasks_10.jsonl", limit=10)
    assert len(tasks) == 10
    for t in tasks:
        assert t.task_id
        assert t.repo
        assert t.base_commit
        assert isinstance(t.issue_number, int)
        assert t.issue_title
        assert t.issue_body
        assert t.test_files


def test_single_file_change_rejects_four_file_pr() -> None:
    pr: dict[str, Any] = {
        "changed_files": ["a.py", "tests/test_a.py", "b.py", "c.py", "d.py"],
    }
    assert single_file_change(pr) is False
    assert has_test_coverage(pr) is True


def test_single_file_change_accepts_src_and_test() -> None:
    pr: dict[str, Any] = {
        "changed_files": ["src/widget.py", "tests/test_widget.py"],
    }
    assert single_file_change(pr) is True


@pytest.mark.asyncio
async def test_build_task_from_mocked_github(builder: GitHubDatasetBuilder) -> None:
    issue: dict[str, Any] = {
        "number": 42,
        "title": "Bug in widget",
        "body": "x" * 120,
        "labels": [{"name": "bug"}],
    }
    pr: dict[str, Any] = {
        "number": 99,
        "title": "Fix widget",
        "body": "fixes #42",
        "merged_at": "2024-06-01T00:00:00Z",
        "base_commit": "abc123def456",
        "changed_files": ["src/widget.py", "tests/test_widget.py"],
    }
    assert passes_all_filters(issue, pr) is True

    pr_wide = {
        **pr,
        "changed_files": ["a.py", "tests/test_widget.py", "b.py", "c.py", "d.py"],
    }
    assert passes_all_filters(issue, pr_wide) is False

    task = await builder.build_task("o/r", issue, pr)
    assert task is not None
    assert isinstance(task, Task)
    assert task.issue_number == 42
    assert len(task.issue_body) >= 100
    assert task.test_files == ["tests/test_widget.py"]
    assert "src/widget.py" not in task.test_files
    assert task.base_commit == "abc123def456"
    assert task.hints_text.startswith("Try patching")


@pytest.mark.asyncio
async def test_fetch_closed_issues_skips_pull_requests(
    builder: GitHubDatasetBuilder,
) -> None:
    issues = await builder.fetch_closed_issues("o/r", limit=10)
    assert len(issues) == 1
    assert issues[0]["number"] == 1


@pytest.mark.asyncio
async def test_fetch_pr_for_issue_finds_fixes_reference(
    builder: GitHubDatasetBuilder,
) -> None:
    pr = await builder.fetch_pr_for_issue("o/r", 42)
    assert pr is not None
    assert pr["base_commit"] == "deadbeef"
    assert pr["changed_files"] == ["tests/test_widget.py"]


@pytest.mark.asyncio
async def test_run_writes_jsonl(
    tmp_path: Path,
    builder_run: GitHubDatasetBuilder,
) -> None:
    out = tmp_path / "built.jsonl"
    tasks = await builder_run.run(str(out), limit=1)
    assert len(tasks) == 1
    loaded = load_tasks(out)
    assert loaded[0].task_id == "r-0007"
    assert loaded[0].test_files == ["tests/test_run.py"]


@pytest.mark.asyncio
async def test_fetch_pr_via_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/issues/5/timeline":
            return httpx.Response(
                200,
                json=[
                    {
                        "event": "cross-referenced",
                        "source": {
                            "issue": {
                                "number": 11,
                                "title": "Fix",
                                "body": "closes #5",
                                "pull_request": {"url": "https://api.github.com/pulls/11"},
                            },
                        },
                    },
                ],
            )
        if request.url.path == "/repos/o/r/pulls/11":
            return httpx.Response(
                200,
                json={
                    "merged_at": "2024-03-01T00:00:00Z",
                    "base": {"sha": "timeline_sha"},
                },
            )
        if request.url.path == "/repos/o/r/pulls/11/files":
            return httpx.Response(200, json=[{"filename": "tests/test_tl.py"}])
        return httpx.Response(404, json={"message": "not mocked"})

    b = _make_builder(monkeypatch, handler)
    pr = await b.fetch_pr_for_issue("o/r", 5)
    assert pr is not None
    assert pr["base_commit"] == "timeline_sha"


@pytest.mark.asyncio
async def test_fetch_pr_returns_none_when_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/timeline"):
            return httpx.Response(200, json=[])
        if request.url.path == "/search/issues":
            return httpx.Response(200, json={"items": []})
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "not mocked"})

    b = _make_builder(monkeypatch, handler)
    assert await b.fetch_pr_for_issue("o/r", 99) is None
