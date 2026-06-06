from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from coding_eval.dataset.schema import TaskResult


class LeaderboardEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    mean_composite_score: float
    mean_test_pass_rate: float
    mean_diff_minimality: float
    mean_complexity_delta: float
    mean_style_score: float
    mean_semantic_score: float
    mean_cost_usd: float
    n_total: int
    n_contaminated: int
    n_clean: int
    contamination_rate: float
    n_errors: int
    total_cost_usd: float
    mean_latency_ms: float


class Leaderboard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "0.1.0"
    seed: str = "seed_50"
    created_at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    entries: tuple[LeaderboardEntry, ...] = ()


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def aggregate(results: list[TaskResult], *, seed: str = "seed_50") -> Leaderboard:
    by_agent: dict[str, list[TaskResult]] = defaultdict(list)
    for result in results:
        by_agent[result.agent_id].append(result)

    entries: list[LeaderboardEntry] = []
    for agent_id in sorted(by_agent):
        agent_results = by_agent[agent_id]
        n_total = len(agent_results)
        n_contaminated = sum(1 for r in agent_results if r.is_contaminated)
        n_errors = sum(1 for r in agent_results if r.error is not None)
        n_clean = n_total - n_contaminated
        contamination_rate = n_contaminated / n_total if n_total else 0.0
        total_cost = sum(r.cost_usd for r in agent_results)

        entries.append(
            LeaderboardEntry(
                agent_id=agent_id,
                mean_composite_score=_mean([r.composite_score for r in agent_results]),
                mean_test_pass_rate=_mean([r.test_pass_rate for r in agent_results]),
                mean_diff_minimality=_mean([r.diff_minimality for r in agent_results]),
                mean_complexity_delta=_mean([r.complexity_delta for r in agent_results]),
                mean_style_score=_mean([r.style_score for r in agent_results]),
                mean_semantic_score=_mean([r.semantic_score for r in agent_results]),
                mean_cost_usd=total_cost / n_total if n_total else 0.0,
                n_total=n_total,
                n_contaminated=n_contaminated,
                n_clean=n_clean,
                contamination_rate=contamination_rate,
                n_errors=n_errors,
                total_cost_usd=total_cost,
                mean_latency_ms=_mean([r.latency_ms for r in agent_results]),
            ),
        )

    entries.sort(key=lambda entry: entry.mean_composite_score, reverse=True)
    return Leaderboard(seed=seed, entries=tuple(entries))


__all__ = ["Leaderboard", "LeaderboardEntry", "aggregate"]
