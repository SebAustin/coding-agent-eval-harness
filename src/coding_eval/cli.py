from __future__ import annotations

from pathlib import Path

import typer

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
) -> None:
    _ = (repos, limit)
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("", encoding="utf-8")

