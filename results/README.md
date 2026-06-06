# Eval run outputs

This directory holds artifacts from `coding-eval run`. Generated files are gitignored except this README.

## Files

| File | Description |
| --- | --- |
| `{agent_id}_results.jsonl` | One `TaskResult` per line for each evaluated task |
| `leaderboard.json` | Machine-readable aggregate metrics per agent |
| `leaderboard.md` | GitHub-renderable markdown leaderboard table |
| `semantic_cache.sqlite` | Cached Claude semantic judge scores (keyed by issue + patch) |

## Example

```bash
set -a && source .env && set +a
uv run coding-eval run --agents claude-code --limit 5 --smoke
```

Commit `leaderboard.md` to share results on GitHub; keep `.env` and per-run JSONL local unless you intend to publish them.
