#!/usr/bin/env python3
"""Fail CI when smoke composite drops more than tolerance vs main baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Max allowed drop in mean smoke composite vs the main baseline before CI fails.
# 0.60 was effectively "never fires" (CODEBASE.md §9.8). At a current max composite
# of ~0.60 and temperature=0 sampling, 0.10 catches a genuine regression while
# tolerating benign run-to-run noise in the mean. Revisit once the leaderboard
# stabilizes on the 50-task set (D1).
REGRESSION_TOLERANCE = 0.10
DEFAULT_AGENT = "claude-code"


def _composite(leaderboard: dict[str, object], agent_id: str) -> float | None:
    entries = leaderboard.get("entries")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("agent_id") == agent_id:
            score = entry.get("mean_composite_score")
            if isinstance(score, int | float):
                return float(score)
    return None


def main() -> None:
    baseline_path = Path(sys.argv[1] if len(sys.argv) > 1 else "baseline/leaderboard.json")
    current_path = Path(sys.argv[2] if len(sys.argv) > 2 else "results/leaderboard.json")
    agent_id = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_AGENT

    if not current_path.is_file():
        print(f"Missing current leaderboard: {current_path}", file=sys.stderr)
        raise SystemExit(1)

    current = json.loads(current_path.read_text(encoding="utf-8"))
    current_score = _composite(current, agent_id)
    if current_score is None:
        print(f"No composite score for {agent_id!r} in {current_path}", file=sys.stderr)
        raise SystemExit(1)

    if not baseline_path.is_file():
        print(f"No baseline at {baseline_path}; skipping regression gate")
        raise SystemExit(0)

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_score = _composite(baseline, agent_id)
    if baseline_score is None:
        print(f"No baseline composite for {agent_id!r}; skipping regression gate")
        raise SystemExit(0)

    drop = baseline_score - current_score
    print(
        f"Regression check ({agent_id}): "
        f"baseline={baseline_score:.3f} current={current_score:.3f} drop={drop:.3f} "
        f"tolerance={REGRESSION_TOLERANCE:.3f}",
    )
    if drop > REGRESSION_TOLERANCE:
        print(
            f"FAIL: composite dropped {drop:.3f} vs main (max allowed {REGRESSION_TOLERANCE:.3f})",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print("Regression gate passed")


if __name__ == "__main__":
    main()
