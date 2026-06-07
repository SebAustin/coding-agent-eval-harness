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

## Results (seed_50, `--seed 42`)

A full 20-task run was executed for both adapters. The funded API credits were
exhausted partway through the (~15x pricier) agentic pass: 8 of the 20 agentic
tasks returned `400 invalid_request_error: credit balance too low` and scored 0.
An errored task scores 0 on *every* axis, so those spurious zeros make the raw
20-task aggregate meaningless for the agentic adapter (it reads -0.065 composite —
an artifact). Compare instead on the **12 tasks where both adapters completed**:

| Axis | claude-code | claude-code-agentic | delta |
|---|---:|---:|---:|
| Composite | 0.689 | 0.817 | **+0.128** |
| Test pass | 0.500 | 0.667 | +0.167 |
| Diff min | 0.897 | 0.963 | +0.066 |
| Complexity | 0.914 | 0.999 | +0.085 |
| Style | 0.887 | 0.954 | +0.067 |
| Semantic | 0.546 | 0.729 | +0.183 |
| Cost/task ($) | 0.066 | 1.015 | +0.949 |

**On tasks it completed, the agentic adapter is a net win (+0.128 composite),
driven by correctness (test pass +0.167, semantic +0.183), at ~15x cost.** The
wins concentrate on exploration / multi-file tasks; easy single-file tasks tie:

| Task | single-shot | agentic | note |
|---|---:|---:|---|
| `typer-0822` | 0.000 | 0.979 | single-shot emitted fake tool tags -> empty patch; agentic patches both files |
| `rich-1876` | 0.501 | 0.970 | multi-file fix |
| `rich-1717` | 0.437 | 0.517 | |
| 8 easy tasks | ~0.99 | ~0.99 | tie |

Caveats: 12-task subset (credits cut the run short — finish the remaining 8 with
more balance for a full-20 number); `temperature=0` is not a seed, so per-task
composite varies ~0.2 between runs — average several runs before treating +0.128 as
definitive; the ~15x cost premium is real and is the price of exploration. Reproduce
with `make eval-compare`.
