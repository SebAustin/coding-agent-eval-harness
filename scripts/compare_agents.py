"""Render a single-shot vs agentic head-to-head from a combined leaderboard.json.

The runner already evaluates multiple agents into one leaderboard, so the
comparison is just: run both, then diff the per-axis means.

    uv run coding-eval run --agents claude-code --agents claude-code-agentic \
        --tasks-file data/tasks/seed_50.jsonl --output-dir results/agentic_compare
    uv run python scripts/compare_agents.py results/agentic_compare/leaderboard.json

Or simply `make eval-compare`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BASE = "claude-code"
AGENTIC = "claude-code-agentic"
AXES: list[tuple[str, str]] = [
    ("Composite", "mean_composite_score"),
    ("Test pass", "mean_test_pass_rate"),
    ("Diff min", "mean_diff_minimality"),
    ("Complexity", "mean_complexity_delta"),
    ("Style", "mean_style_score"),
    ("Semantic", "mean_semantic_score"),
    ("Cost/task ($)", "mean_cost_usd"),
]


def _entry(entries: list[dict[str, Any]], agent_id: str) -> dict[str, Any] | None:
    return next((e for e in entries if e.get("agent_id") == agent_id), None)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("results/agentic_compare/leaderboard.json")
    if not path.is_file():
        msg = f"leaderboard not found: {path} — run the eval first (see module docstring)"
        raise SystemExit(msg)

    entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    base = _entry(entries, BASE)
    agentic = _entry(entries, AGENTIC)
    if base is None or agentic is None:
        msg = f"need both {BASE!r} and {AGENTIC!r} in {path}; run with --agents for each"
        raise SystemExit(msg)

    print(f"# Agent comparison ({base['n_total']} tasks)\n")
    print(f"| Axis | {BASE} | {AGENTIC} | delta |")
    print("|---|---:|---:|---:|")
    for label, key in AXES:
        b, a = float(base[key]), float(agentic[key])
        print(f"| {label} | {b:.3f} | {a:.3f} | {a - b:+.3f} |")

    delta = float(agentic["mean_composite_score"]) - float(base["mean_composite_score"])
    verdict = "agentic wins" if delta > 0 else ("tie" if delta == 0 else "single-shot wins")
    print(f"\nComposite delta: {delta:+.3f} ({verdict}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
