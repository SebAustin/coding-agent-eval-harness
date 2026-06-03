from __future__ import annotations

from pathlib import Path

from coding_eval.dataset.io import dump_tasks, iter_jsonl, load_tasks
from coding_eval.dataset.schema import Task


def test_dump_and_load_roundtrip(tmp_path: Path) -> None:
    task = Task(
        task_id="t-1",
        repo="o/r",
        base_commit="abc",
        issue_number=1,
        issue_title="title",
        issue_body="body" * 20,
        test_files=["tests/test_x.py"],
    )
    path = tmp_path / "tasks.jsonl"
    dump_tasks([task], path)
    rows = list(iter_jsonl(path))
    assert len(rows) == 1
    loaded = load_tasks(path)
    assert loaded[0] == task
