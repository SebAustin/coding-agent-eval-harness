from __future__ import annotations

import asyncio
import os
from pathlib import Path

import structlog
import typer

from coding_eval.dataset.builder import GitHubDatasetBuilder

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

app = typer.Typer(add_completion=False)


@app.command()
def main(
    repo: list[str] = typer.Option(..., "--repo"),
    limit: int = typer.Option(50, "--limit"),
    output: str = typer.Option("data/tasks/built.jsonl", "--output"),
    max_pr_pages: int = typer.Option(
        5,
        "--max-pr-pages",
        help="Pages of closed PRs to scan per repo (100 PRs/page)",
    ),
    max_merged_search_pages: int = typer.Option(
        5,
        "--max-merged-search-pages",
        help="Pages of merged-PR search results per repo",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Log filter rejection reasons",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="GitHub token (default: GITHUB_TOKEN env)",
    ),
) -> None:
    github_token = token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        typer.echo("GITHUB_TOKEN is required (or pass --token)", err=True)
        raise typer.Exit(code=1)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    builder = GitHubDatasetBuilder(
        github_token=github_token,
        repos=list(repo),
        max_pr_pages=max_pr_pages,
        max_merged_search_pages=max_merged_search_pages,
        log_filter_misses=verbose,
    )
    tasks = asyncio.run(builder.run(str(out), limit=limit))
    typer.echo(f"Wrote {len(tasks)} tasks to {out}")
    if len(tasks) < limit:
        typer.echo(
            f"Warning: only {len(tasks)} tasks passed filters (requested {limit}).",
            err=True,
        )


if __name__ == "__main__":
    app()
