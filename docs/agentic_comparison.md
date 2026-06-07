# Agentic vs single-shot comparison

Whether the tool-using `claude-code-agentic` adapter actually beats the single-shot
`claude-code` adapter is an empirical question, not an assumption. This page is the
reproducible experiment that answers it.

## Hypothesis

- `claude-code` (single-shot) sends a fixed slice of repo context and asks for one
  diff. It fails when the fix spans files the context heuristics never surfaced (the
  model hallucinates code it cannot see).
- `claude-code-agentic` explores the clone with read-only `read_file` / `grep` /
  `list_dir` before patching. It should **raise `test_pass_rate` and
  `semantic_score` on multi-file tasks at a higher cost/task** (~$1–2 vs ~$0.09 and
  more latency), and should not regress single-file tasks beyond noise.

## How to run

```bash
make build-sandbox            # once
export ANTHROPIC_API_KEY=...  # funded key
make eval-compare             # full seed_50; override TASKS=... for a subset
```

`make eval-compare` runs both agents into one leaderboard
(`results/agentic_compare/leaderboard.json`) and prints a per-axis delta via
`scripts/compare_agents.py`. To scope it down while iterating:

```bash
make eval-compare TASKS=data/tasks/typer-0822.jsonl
# or, directly, on a sample:
uv run coding-eval run --agents claude-code --agents claude-code-agentic --limit 10
uv run python scripts/compare_agents.py results/leaderboard.json
```

## What to read

The renderer reports per-axis means for both agents and the agentic−single-shot
delta. Interpretation guidance:

| Signal | Meaning |
|---|---|
| `Composite` delta > 0 | Agentic is a net win at the rubric's weighting. |
| `Test pass` / `Semantic` up, `Composite` down | Correctness improved but cost/minimality dragged the weighted score — expected on easy tasks. |
| `Cost/task` | The price of exploration; bounded by `MAX_TURNS` + `MAX_COST_USD` in the agentic adapter. |

Because `temperature=0` is not a seed, per-task composite varies up to ~0.2 between
runs (see [methodology §Limitations](methodology.md)). Average several runs, or compare
on a fixed task set, before reading rankings into a single run.

## Evidence so far

| Scope | Result |
|---|---|
| `typer-0822` (multi-file: `_completion_shared.py` + `_completion_classes.py`) | single-shot: empty patch (fabricated tool tags) → composite 0.0; agentic: applicable patch, **10/10 completion tests pass** |

The full-dataset comparison (the table `compare_agents.py` emits) is pending an API
credit / CI-capacity window; the command above reproduces it.
