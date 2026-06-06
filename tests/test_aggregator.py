from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from coding_eval.dataset.schema import TaskResult
from coding_eval.leaderboard.aggregator import Leaderboard, LeaderboardEntry, aggregate
from coding_eval.leaderboard.render import write_leaderboard


def _result(
    *,
    agent_id: str = "claude-code",
    composite: float = 0.5,
    contaminated: bool = False,
    error: str | None = None,
    cost: float = 0.01,
    latency: float = 100.0,
) -> TaskResult:
    return TaskResult(
        task_id=f"task-{composite}",
        agent_id=agent_id,
        patch="",
        test_pass_rate=composite,
        diff_minimality=composite,
        complexity_delta=composite,
        style_score=composite,
        semantic_score=composite,
        composite_score=composite,
        is_contaminated=contaminated,
        contamination_similarity=0.9 if contaminated else 0.1,
        latency_ms=latency,
        cost_usd=cost,
        error=error,
    )


def test_aggregate_mean_composite_for_three_results() -> None:
    results = [
        _result(composite=0.6),
        _result(composite=0.8),
        _result(composite=1.0),
    ]
    summary = aggregate(results)
    assert len(summary.entries) == 1
    entry = summary.entries[0]
    assert entry.agent_id == "claude-code"
    assert entry.n_total == 3
    assert entry.mean_composite_score == pytest.approx(0.8)
    assert entry.mean_test_pass_rate == pytest.approx(0.8)
    assert entry.total_cost_usd == pytest.approx(0.03)
    assert entry.mean_cost_usd == pytest.approx(0.01)


def test_aggregate_contamination_rate() -> None:
    results = [
        _result(composite=0.5, contaminated=True),
        _result(composite=0.7, contaminated=False),
        _result(composite=0.9, contaminated=False),
        _result(composite=0.4, contaminated=True),
    ]
    entry = aggregate(results).entries[0]
    assert entry.n_total == 4
    assert entry.n_contaminated == 2
    assert entry.n_clean == 2
    assert entry.contamination_rate == pytest.approx(0.5)
    assert entry.n_errors == 0


def test_aggregate_counts_errors() -> None:
    results = [
        _result(error="clone failed"),
        _result(error=None),
    ]
    entry = aggregate(results).entries[0]
    assert entry.n_errors == 1


def test_leaderboard_json_schema(tmp_path: Path) -> None:
    path = tmp_path / "out"
    summary = aggregate([_result(composite=1.0)])
    write_leaderboard(summary, str(path))

    parsed = json.loads((path / "leaderboard.json").read_text(encoding="utf-8"))
    assert set(parsed.keys()) == {"created_at", "entries", "seed", "version"}
    assert isinstance(parsed["entries"], list)

    entry = LeaderboardEntry.model_validate(parsed["entries"][0])
    assert entry.agent_id == "claude-code"
    assert entry.mean_composite_score == 1.0

    Leaderboard.model_validate(parsed)

    md = (path / "leaderboard.md").read_text(encoding="utf-8")
    assert "| Agent | Composite |" in md
    assert "claude-code" in md


def test_leaderboard_entry_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LeaderboardEntry.model_validate(
            {
                "agent_id": "a",
                "mean_composite_score": 1.0,
                "mean_test_pass_rate": 1.0,
                "mean_diff_minimality": 1.0,
                "mean_complexity_delta": 1.0,
                "mean_style_score": 1.0,
                "mean_semantic_score": 1.0,
                "mean_cost_usd": 0.0,
                "n_total": 1,
                "n_contaminated": 0,
                "n_clean": 1,
                "contamination_rate": 0.0,
                "n_errors": 0,
                "total_cost_usd": 0.0,
                "mean_latency_ms": 1.0,
                "extra": "nope",
            },
        )


def test_aggregate_empty_results() -> None:
    summary = aggregate([])
    assert summary.entries == ()


def test_aggregate_sorts_by_composite_desc() -> None:
    results = [
        _result(agent_id="slow", composite=0.2),
        _result(agent_id="fast", composite=0.9),
    ]
    summary = aggregate(results)
    assert [entry.agent_id for entry in summary.entries] == ["fast", "slow"]
