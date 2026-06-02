from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class LeaderboardEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    n_tasks: int
    n_failed: int
    contamination_rate: float
    mean_test_pass_rate: float
    mean_diff_minimality: float
    mean_complexity_delta: float
    mean_style_score: float
    mean_semantic_score: float
    mean_composite_score: float
    mean_cost_usd: float
    mean_latency_ms: float


class Leaderboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "0.1.0"
    seed: str = "seed_50"
    created_at: str = ""
    entries: list[LeaderboardEntry] = Field(default_factory=list)


def write_leaderboard_json(leaderboard: Leaderboard, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(leaderboard.model_dump(), f, indent=2, sort_keys=True)
        f.write("\n")

