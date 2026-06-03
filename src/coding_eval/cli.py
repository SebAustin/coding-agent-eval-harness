from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from coding_eval.dataset.builder import GitHubDatasetBuilder
from coding_eval.dataset.io import load_tasks
from coding_eval.results.aggregator import Leaderboard, write_leaderboard_json

app = typer.Typer(name="coding-eval", add_completion=False)


@app.command()
def run(
    agents: list[str] = typer.Option(["claude-code"], "--agents"),
    limit: int = typer.Option(0, "--limit", help="0 = all tasks"),
    seed: int = typer.Option(42, "--seed"),
    smoke: bool = typer.Option(False, "--smoke", help="5-task smoke only"),
    output_dir: str = typer.Option("results", "--output-dir"),
) -> None:
    _ = (agents, seed)
    tasks_path = Path("data/tasks/seed_50.jsonl")
    tasks = load_tasks(tasks_path, limit=(5 if smoke else limit))
    _ = tasks

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_leaderboard_json(Leaderboard(), out_dir / "leaderboard.json")


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

