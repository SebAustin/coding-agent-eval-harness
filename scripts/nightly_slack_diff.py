#!/usr/bin/env python3
"""Post leaderboard diff to Slack when SLACK_WEBHOOK_URL is set."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx


def _load(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _agent_rows(leaderboard: dict[str, object]) -> dict[str, dict[str, object]]:
    entries = leaderboard.get("entries")
    if not isinstance(entries, list):
        return {}
    rows: dict[str, dict[str, object]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("agent_id"), str):
            rows[entry["agent_id"]] = entry
    return rows


def _format_diff(before: dict[str, object], after: dict[str, object]) -> str:
    old_rows = _agent_rows(before)
    new_rows = _agent_rows(after)
    agents = sorted(set(old_rows) | set(new_rows))
    if not agents:
        return "No leaderboard entries to compare."

    lines = ["*Nightly leaderboard update*", ""]
    for agent_id in agents:
        old = old_rows.get(agent_id, {})
        new = new_rows.get(agent_id, {})
        old_score = old.get("mean_composite_score", "n/a")
        new_score = new.get("mean_composite_score", "n/a")
        if isinstance(old_score, int | float) and isinstance(new_score, int | float):
            delta = float(new_score) - float(old_score)
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"• `{agent_id}`: {old_score:.3f} → {new_score:.3f} ({sign}{delta:.3f})",
            )
        else:
            lines.append(f"• `{agent_id}`: {old_score} → {new_score}")
    return "\n".join(lines)


def main() -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        print("SLACK_WEBHOOK_URL not set; skipping Slack notification")
        raise SystemExit(0)

    before_path = Path(sys.argv[1] if len(sys.argv) > 1 else "results/leaderboard.before.json")
    after_path = Path(sys.argv[2] if len(sys.argv) > 2 else "results/leaderboard.json")
    text = _format_diff(_load(before_path), _load(after_path))

    response = httpx.post(webhook, json={"text": text}, timeout=30.0)
    response.raise_for_status()
    print("Posted leaderboard diff to Slack")


if __name__ == "__main__":
    main()
