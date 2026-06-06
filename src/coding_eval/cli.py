from __future__ import annotations

import asyncio
import os
import random
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import anthropic
import numpy as np
import structlog
import typer
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from coding_eval.agents import AgentAdapter, get_adapter
from coding_eval.dataset.builder import GitHubDatasetBuilder
from coding_eval.dataset.contamination import (
    MODEL_NAME,
    compute_contamination,
    load_swebench_embeddings,
)
from coding_eval.dataset.io import dump_task_results, load_tasks
from coding_eval.dataset.repos import RepoCloneError, clone_repo_at_commit
from coding_eval.dataset.schema import Task, TaskResult
from coding_eval.leaderboard.aggregator import aggregate
from coding_eval.leaderboard.render import print_leaderboard_table, write_leaderboard
from coding_eval.patching.git_apply import check_unified_diff
from coding_eval.rubric.scorer import RubricScores, score as score_rubric
from coding_eval.sandbox.deps import prepare_offline_wheels
from coding_eval.sandbox.runner import DockerSandbox, SandboxResult

log = structlog.get_logger(__name__)

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

DEFAULT_TASKS_PATH = Path("data/tasks/seed_50.jsonl")
DEFAULT_EMBEDDINGS_PATH = Path("data/contamination/swebench_train_embeddings.npz")

app = typer.Typer(name="coding-eval", add_completion=False)


def _shuffle_tasks(tasks: list[Task], seed: int) -> list[Task]:
    shuffled = list(tasks)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def _select_tasks(
    tasks: list[Task],
    *,
    smoke: bool,
    limit: int,
) -> list[Task]:
    if smoke:
        return tasks[:5]
    if limit > 0:
        return tasks[:limit]
    return tasks


def _warn_placeholder_commits(tasks: list[Task]) -> None:
    bad = [task for task in tasks if len(task.base_commit) < 12]
    if not bad:
        return
    ids = ", ".join(task.task_id for task in bad[:5])
    typer.echo(
        f"Warning: {len(bad)} task(s) have placeholder base_commit SHAs ({ids}). "
        "Run build-dataset or point --tasks-file at data/tasks/built_15.jsonl.",
        err=True,
    )


def _failed_sandbox_result(message: str) -> SandboxResult:
    return SandboxResult(
        exit_code=1,
        stdout="",
        stderr=message,
        duration_ms=0.0,
        timed_out=False,
    )


def _zero_rubric() -> RubricScores:
    return RubricScores(
        test_pass_rate=0.0,
        diff_minimality=0.0,
        complexity_delta=0.0,
        style_score=0.0,
        semantic_score=0.0,
    )


async def _eval_task(
    *,
    task: Task,
    agent_id: str,
    adapter: AgentAdapter,
    sandbox: DockerSandbox,
    anthropic_client: anthropic.AsyncAnthropic,
    swebench_embeddings: NDArray[np.float32],
    embed_model: SentenceTransformer,
    semantic_cache_path: Path,
    run_id: str,
    output_dir: Path,
) -> TaskResult:
    start = time.perf_counter()
    error: str | None = None
    patch = ""
    cost_usd = 0.0
    rubric = _zero_rubric()
    sandbox_result = _failed_sandbox_result("no patch produced")
    is_contaminated = False
    contamination_similarity = 0.0
    repo_dir = Path(tempfile.mkdtemp(prefix="coding-eval-repo-"))

    try:
        is_contaminated, contamination_similarity = compute_contamination(
            task.issue_body,
            swebench_embeddings,
            embed_model,
        )
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
        solve_result = await adapter.solve(task, str(repo_dir))
        patch = solve_result.patch
        cost_usd = solve_result.cost_usd
        if not patch.strip() and solve_result.raw_response.strip():
            raw_path = output_dir / f"{task.task_id}_{agent_id}_raw.txt"
            raw_path.write_text(solve_result.raw_response, encoding="utf-8")
            log.info("eval.empty_patch_raw_saved", task_id=task.task_id, path=str(raw_path))
        if patch.strip():
            apply_ok, apply_error = await asyncio.to_thread(
                check_unified_diff,
                str(repo_dir),
                patch,
            )
            if apply_ok:
                sandbox_result = await sandbox.run_patch(
                    str(repo_dir),
                    patch,
                    task.test_files,
                )
                if sandbox_result.exit_code != 0:
                    tail = sandbox_result.stderr or sandbox_result.stdout
                    log.info(
                        "eval.sandbox_failed",
                        task_id=task.task_id,
                        exit_code=sandbox_result.exit_code,
                        output_tail=tail[-800:] if tail else "",
                    )
            else:
                log.info(
                    "eval.sandbox_skipped",
                    task_id=task.task_id,
                    reason="apply_check_failed",
                    error=apply_error[:500],
                )
                sandbox_result = _failed_sandbox_result(apply_error)
        rubric = await score_rubric(
            task.issue_body,
            patch,
            sandbox_result,
            str(repo_dir),
            anthropic_client,
            issue_title=task.issue_title,
            semantic_cache_path=str(semantic_cache_path),
        )
    except RepoCloneError as exc:
        error = str(exc)
        log.warning("eval.clone_failed", task_id=task.task_id, error=error)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        log.warning("eval.task_failed", task_id=task.task_id, error=error)
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)

    latency_ms = (time.perf_counter() - start) * 1000.0
    return TaskResult(
        task_id=task.task_id,
        agent_id=agent_id,
        patch=patch,
        test_pass_rate=rubric.test_pass_rate,
        diff_minimality=rubric.diff_minimality,
        complexity_delta=rubric.complexity_delta,
        style_score=rubric.style_score,
        semantic_score=rubric.semantic_score,
        composite_score=rubric.composite,
        is_contaminated=is_contaminated,
        contamination_similarity=contamination_similarity,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        error=error,
        run_id=run_id,
    )


async def _run_eval_async(
    *,
    agents: list[str],
    limit: int,
    seed: int,
    smoke: bool,
    output_dir: str,
    tasks_path: Path,
    embeddings_path: Path,
) -> None:
    tasks = _shuffle_tasks(load_tasks(tasks_path), seed)
    tasks = _select_tasks(tasks, smoke=smoke, limit=limit)
    _warn_placeholder_commits(tasks)
    if not tasks:
        typer.echo("No tasks to evaluate.", err=True)
        raise typer.Exit(code=1)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]

    swebench_embeddings = await asyncio.to_thread(
        load_swebench_embeddings,
        str(embeddings_path),
    )
    embed_model = await asyncio.to_thread(SentenceTransformer, MODEL_NAME)
    anthropic_client = anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    sandbox = DockerSandbox()
    semantic_cache_path = out_dir / "semantic_cache.sqlite"

    all_results: list[TaskResult] = []
    for agent_id in agents:
        log.info("eval.agent_start", agent_id=agent_id, n_tasks=len(tasks))
        adapter = get_adapter(agent_id, api_key=os.environ.get("ANTHROPIC_API_KEY"))
        agent_results: list[TaskResult] = []
        for task in tasks:
            log.info("eval.task_start", agent_id=agent_id, task_id=task.task_id)
            result = await _eval_task(
                task=task,
                agent_id=agent_id,
                adapter=adapter,
                sandbox=sandbox,
                anthropic_client=anthropic_client,
                swebench_embeddings=swebench_embeddings,
                embed_model=embed_model,
                semantic_cache_path=semantic_cache_path,
                run_id=run_id,
                output_dir=out_dir,
            )
            agent_results.append(result)
            all_results.append(result)
            log.info(
                "eval.task_done",
                agent_id=agent_id,
                task_id=task.task_id,
                composite=result.composite_score,
                error=result.error,
            )
        dump_task_results(agent_results, out_dir / f"{agent_id}_results.jsonl")

    summary = aggregate(all_results, seed=tasks_path.stem)
    write_leaderboard(summary, output_dir)
    print_leaderboard_table(summary)


@app.command()
def run(
    agents: list[str] = typer.Option(["claude-code"], "--agents"),
    limit: int = typer.Option(0, "--limit", help="0 = all tasks"),
    seed: int = typer.Option(42, "--seed"),
    smoke: bool = typer.Option(False, "--smoke", help="5-task smoke only"),
    output_dir: str = typer.Option("results", "--output-dir"),
    tasks_file: str = typer.Option(
        str(DEFAULT_TASKS_PATH),
        "--tasks-file",
        help="JSONL task file",
    ),
    embeddings_file: str = typer.Option(
        str(DEFAULT_EMBEDDINGS_PATH),
        "--embeddings-file",
        help="SWE-bench train embeddings NPZ",
    ),
) -> None:
    asyncio.run(
        _run_eval_async(
            agents=agents,
            limit=limit,
            seed=seed,
            smoke=smoke,
            output_dir=output_dir,
            tasks_path=Path(tasks_file),
            embeddings_path=Path(embeddings_file),
        ),
    )


@app.command()
def build_dataset(
    repos: list[str] = typer.Option(..., "--repo"),
    limit: int = typer.Option(50, "--limit"),
    output: str = typer.Option("data/tasks/seed_50.jsonl", "--output"),
    max_pr_pages: int = typer.Option(5, "--max-pr-pages"),
    max_merged_search_pages: int = typer.Option(3, "--max-merged-search-pages"),
    verbose: bool = typer.Option(False, "--verbose"),
    token: str | None = typer.Option(None, "--token"),
) -> None:
    github_token = token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        typer.echo("GITHUB_TOKEN is required (or pass --token)", err=True)
        raise typer.Exit(code=1)

    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    builder = GitHubDatasetBuilder(
        github_token=github_token,
        repos=repos,
        max_pr_pages=max_pr_pages,
        max_merged_search_pages=max_merged_search_pages,
        log_filter_misses=verbose,
    )
    asyncio.run(builder.run(str(p), limit=limit))
