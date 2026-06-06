"""Targeted live confirmation that the agentic adapter solves typer-0822.

Loads .env, clones typer at the task's base commit, runs the real tool-using
adapter, and checks the produced patch applies. Bypasses Docker/embeddings/the
semantic judge so it only exercises (and bills) host-side patch generation.

Run: ./.venv/bin/python3 scripts/confirm_typer_0822.py
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from coding_eval.agents.claude_code_agentic import ClaudeCodeAgenticAdapter
from coding_eval.dataset.repos import clone_repo_at_commit
from coding_eval.dataset.schema import Task
from coding_eval.patching.git_apply import check_unified_diff

TASK_ID = "typer-0822"
FAKE_TAGS = ("<file_search>", "<read_files>", "<search>")


def _load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _load_task(tasks_path: Path) -> Task:
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["task_id"] == TASK_ID:
            return Task(**record)
    msg = f"{TASK_ID} not found in {tasks_path}"
    raise SystemExit(msg)


async def main() -> int:
    root = Path(__file__).resolve().parent.parent
    _load_env(root / ".env")
    task = _load_task(root / "data" / "tasks" / "seed_50.jsonl")

    repo_dir = Path(tempfile.mkdtemp(prefix="confirm-typer-0822-"))
    print(f"Cloning {task.repo}@{task.base_commit[:12]} ...")
    clone_repo_at_commit(task.repo, task.base_commit, repo_dir)

    adapter = ClaudeCodeAgenticAdapter(api_key=os.environ["ANTHROPIC_API_KEY"])
    print("Running agentic adapter (real model + tools) ...")
    result = await adapter.solve(task, str(repo_dir))

    fake = [tag for tag in FAKE_TAGS if tag in result.raw_response]
    files = [ln for ln in result.patch.splitlines() if ln.startswith("--- ")]
    if result.patch.strip():
        applies, apply_err = check_unified_diff(str(repo_dir), result.patch)
    else:
        applies, apply_err = False, "empty patch"

    print("\n================ RESULT ================")
    print(f"cost_usd:        {result.cost_usd:.4f}")
    print(f"patch non-empty: {bool(result.patch.strip())}")
    print(f"files touched:   {len(files)} -> {[f.removeprefix('--- a/') for f in files]}")
    print(f"fake tool tags:  {fake or 'none'}")
    print(f"git apply check: {'PASS' if applies else 'FAIL: ' + apply_err[:300]}")
    print("========================================\n")
    if result.patch.strip():
        print(result.patch)

    raw_path = root / "results" / "typer-0822_claude-code-agentic_raw.txt"
    raw_path.write_text(result.raw_response, encoding="utf-8")
    print(f"(raw model text saved to {raw_path.relative_to(root)})")

    ok = bool(result.patch.strip()) and applies and not fake
    print(f"\nACCEPTANCE (applicable patch, no fake tags): {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
