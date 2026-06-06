from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from coding_eval.leaderboard.aggregator import Leaderboard


def write_leaderboard(summary: Leaderboard, output_dir: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "leaderboard.json"
    json_path.write_text(
        json.dumps(summary.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )

    md_path = out / "leaderboard.md"
    md_path.write_text(_render_markdown(summary), encoding="utf-8")


def print_leaderboard_table(summary: Leaderboard) -> None:
    table = Table(title="Coding Agent Eval Leaderboard")
    table.add_column("Agent")
    table.add_column("Composite", justify="right")
    table.add_column("Test pass", justify="right")
    table.add_column("Diff min", justify="right")
    table.add_column("Complexity", justify="right")
    table.add_column("Style", justify="right")
    table.add_column("Semantic", justify="right")
    table.add_column("Cost/task", justify="right")
    table.add_column("n_clean", justify="right")
    table.add_column("Contamination%", justify="right")

    for entry in summary.entries:
        table.add_row(
            entry.agent_id,
            f"{entry.mean_composite_score:.2f}",
            f"{entry.mean_test_pass_rate:.2f}",
            f"{entry.mean_diff_minimality:.2f}",
            f"{entry.mean_complexity_delta:.2f}",
            f"{entry.mean_style_score:.2f}",
            f"{entry.mean_semantic_score:.2f}",
            f"${entry.mean_cost_usd:.3f}",
            str(entry.n_clean),
            f"{entry.contamination_rate * 100:.1f}%",
        )

    Console().print(table)


def _render_markdown(summary: Leaderboard) -> str:
    lines = [
        "# Leaderboard",
        "",
        f"Seed: `{summary.seed}` · Version: `{summary.version}` · "
        f"Generated: `{summary.created_at}`",
        "",
        "| Agent | Composite | Test pass | Diff min | Complexity | Style | "
        "Semantic | Cost/task | n_clean | Contamination% |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for entry in summary.entries:
        lines.append(
            "| "
            f"{entry.agent_id} | "
            f"{entry.mean_composite_score:.2f} | "
            f"{entry.mean_test_pass_rate:.2f} | "
            f"{entry.mean_diff_minimality:.2f} | "
            f"{entry.mean_complexity_delta:.2f} | "
            f"{entry.mean_style_score:.2f} | "
            f"{entry.mean_semantic_score:.2f} | "
            f"${entry.mean_cost_usd:.3f} | "
            f"{entry.n_clean} | "
            f"{entry.contamination_rate * 100:.1f}% |",
        )
    lines.append("")
    return "\n".join(lines)


__all__ = ["print_leaderboard_table", "write_leaderboard"]
