from __future__ import annotations

from pathlib import Path

from coding_eval.dataset.io import dump_task_results, dump_tasks, iter_jsonl, load_tasks
from coding_eval.dataset.schema import Task, TaskResult


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


def test_dump_task_results_roundtrip(tmp_path: Path) -> None:
    result = TaskResult(
        task_id="t-1",
        agent_id="claude-code",
        patch="--- a/x\n+++ b/x\n",
        test_pass_rate=1.0,
        diff_minimality=1.0,
        complexity_delta=1.0,
        style_score=1.0,
        semantic_score=1.0,
        composite_score=1.0,
        is_contaminated=False,
        contamination_similarity=0.0,
        latency_ms=1.0,
        cost_usd=0.0,
    )
    path = tmp_path / "results.jsonl"
    dump_task_results([result], path)
    rows = list(iter_jsonl(path))
    assert rows[0]["task_id"] == "t-1"
    assert TaskResult.model_validate(rows[0]) == result
