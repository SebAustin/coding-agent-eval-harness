"""Re-run the saved typer-0822 patch through the Docker sandbox.

Isolates the sandbox/test outcome from model nondeterminism: it reuses the patch
the agentic adapter already produced (results/typer0822_run/...) instead of
calling the model again. Used to confirm the test result after adding coverage
to the sandbox image.

Run: ./.venv/bin/python3 scripts/sandbox_check_typer_0822.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from coding_eval.dataset.repos import clone_repo_at_commit
from coding_eval.dataset.schema import Task
from coding_eval.sandbox.deps import prepare_offline_wheels
from coding_eval.sandbox.runner import DockerSandbox

TASK_ID = "typer-0822"


def _load_task(path: Path) -> Task:
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["task_id"] == TASK_ID:
            return Task(**record)
    msg = f"{TASK_ID} not found in {path}"
    raise SystemExit(msg)


async def main() -> int:
    root = Path(__file__).resolve().parent.parent
    task = _load_task(root / "data" / "tasks" / "typer-0822.jsonl")
    results = root / "results" / "typer0822_run" / "claude-code-agentic_results.jsonl"
    patch = json.loads(results.read_text(encoding="utf-8").splitlines()[0])["patch"]
    if not patch.strip():
        msg = "no saved patch to test"
        raise SystemExit(msg)

    repo_dir = Path(tempfile.mkdtemp(prefix="sandbox-typer-0822-"))
    print(f"Cloning {task.repo}@{task.base_commit[:12]} ...")
    clone_repo_at_commit(task.repo, task.base_commit, repo_dir)
    prepare_offline_wheels(repo_dir, repo_id=task.repo, commit=task.base_commit)

    print("Running tests in sandbox (coverage-enabled image) ...")
    sandbox = DockerSandbox()
    result = await sandbox.run_patch(str(repo_dir), patch, task.test_files)

    print(f"\nexit_code: {result.exit_code}  timed_out: {result.timed_out}")
    print("=== output tail ===")
    print((result.stdout or result.stderr)[-2500:])
    print(f"\nTESTS: {'PASS' if result.exit_code == 0 else 'FAIL'}")
    return 0 if result.exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
