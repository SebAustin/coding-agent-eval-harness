from __future__ import annotations

import json
from pathlib import Path

from coding_eval.results.aggregator import Leaderboard, LeaderboardEntry, write_leaderboard_json


def test_leaderboard_json_schema(tmp_path: Path) -> None:
    lb = Leaderboard(
        entries=[
            LeaderboardEntry(
                agent_id="a",
                n_tasks=1,
                n_failed=0,
                contamination_rate=0.0,
                mean_test_pass_rate=1.0,
                mean_diff_minimality=1.0,
                mean_complexity_delta=1.0,
                mean_style_score=1.0,
                mean_semantic_score=1.0,
                mean_composite_score=1.0,
                mean_cost_usd=0.0,
                mean_latency_ms=1.0,
            )
        ]
    )
    out = tmp_path / "leaderboard.json"
    write_leaderboard_json(lb, out)

    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert set(parsed.keys()) == {"created_at", "entries", "seed", "version"}
    assert isinstance(parsed["entries"], list)
    assert parsed["entries"][0]["agent_id"] == "a"

