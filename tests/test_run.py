from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from coding_eval.cli import app
from coding_eval.dataset.schema import TaskResult
from coding_eval.leaderboard.aggregator import aggregate
from coding_eval.leaderboard.render import print_leaderboard_table, write_leaderboard


def test_run_smoke_command_invokes_eval(tmp_path: Path) -> None:
    runner = CliRunner()
    with patch("coding_eval.cli._run_eval_async", new_callable=AsyncMock) as mock_run:
        result = runner.invoke(
            app,
            [
                "run",
                "--agents",
                "claude-code",
                "--limit",
                "5",
                "--smoke",
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    mock_run.assert_awaited_once()


def test_run_smoke_writes_leaderboard(tmp_path: Path) -> None:
    results = [
        TaskResult(
            task_id="t1",
            agent_id="claude-code",
            patch="",
            test_pass_rate=0.5,
            diff_minimality=0.5,
            complexity_delta=0.5,
            style_score=0.5,
            semantic_score=0.5,
            composite_score=0.5,
            is_contaminated=False,
            contamination_similarity=0.1,
            latency_ms=10.0,
            cost_usd=0.01,
        ),
    ]
    summary = aggregate(results, seed="seed_50")
    write_leaderboard(summary, str(tmp_path))
    print_leaderboard_table(summary)
    assert (tmp_path / "leaderboard.json").is_file()
    assert (tmp_path / "leaderboard.md").is_file()
