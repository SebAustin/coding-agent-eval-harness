from __future__ import annotations

from pathlib import Path

from coding_eval.dataset.io import load_tasks


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

