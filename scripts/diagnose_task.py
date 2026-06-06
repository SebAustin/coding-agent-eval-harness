#!/usr/bin/env -S uv run python
"""Re-run sandbox apply+test for a task patch saved in results JSONL."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from coding_eval.dataset.io import load_tasks
from coding_eval.dataset.repos import clone_repo_at_commit
from coding_eval.patching.extract import extract_unified_patch
from coding_eval.sandbox.deps import prepare_offline_wheels
from coding_eval.sandbox.runner import DockerSandbox


def _load_patch(results_path: Path, task_id: str) -> str:
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("task_id") == task_id:
            return str(row.get("patch", ""))
    msg = f"task_id {task_id!r} not found in {results_path}"
    raise SystemExit(msg)


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="Task id, e.g. typer-0127")
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/claude-code_results.jsonl"),
    )
    parser.add_argument(
        "--tasks-file",
        type=Path,
        default=Path("data/tasks/seed_50.jsonl"),
    )
    args = parser.parse_args()

    raw_patch = _load_patch(args.results, args.task_id)
    patch = extract_unified_patch(raw_patch) or raw_patch
    task = next(t for t in load_tasks(args.tasks_file) if t.task_id == args.task_id)

    repo_dir = Path(tempfile.mkdtemp(prefix="coding-eval-diagnose-"))
    try:
        await asyncio.to_thread(
            clone_repo_at_commit,
            task.repo,
            task.base_commit,
            repo_dir,
        )
        await asyncio.to_thread(
            prepare_offline_wheels,
            repo_dir,
            repo_id=task.repo,
            commit=task.base_commit,
        )
        sandbox = DockerSandbox()
        result = await sandbox.run_patch(str(repo_dir), patch, task.test_files)
        print(f"exit_code={result.exit_code} timed_out={result.timed_out}")
        if result.stdout:
            print("--- stdout ---")
            print(result.stdout)
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr)
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(_main())
