# Methodology

This document describes how tasks are selected, how contamination is detected, how the
five-axis rubric is weighted, and which judge model is used. For axis-level formulas see
[rubric_design.md](rubric_design.md). For contamination statistics and threshold tuning see
[contamination_analysis.md](contamination_analysis.md).

## Task selection

### Source repositories

Tasks are real merged GitHub pull requests paired with their closing issues. The current
`seed_50` corpus draws from:

| Repository | Rationale |
| --- | --- |
| [Textualize/rich](https://github.com/Textualize/rich) | Mature Python library, high-quality issue templates, fast pytest suite |
| [fastapi/typer](https://github.com/fastapi/typer) | CLI framework with clear bug reports and focused test files |

Both repos use pytest, have permissive licenses, and ship reproducible `pyproject.toml` /
`setup.cfg` layouts that clone cleanly at pinned commits.

Rebuild or extend the corpus with:

```bash
uv run coding-eval build-dataset \
  --repo Textualize/rich \
  --repo fastapi/typer \
  --limit 50 \
  --output data/tasks/seed_50.jsonl
```

Implementation: `src/coding_eval/dataset/builder.py`, filters in
`src/coding_eval/dataset/filters.py`.

### Filter criteria

Every candidate issue–PR pair must pass **all** of the following:

| Filter | Rule |
| --- | --- |
| Bug label | Issue has a `bug` label, `[BUG]` in title, or matched a bug search query |
| Issue body | ≥ 100 characters of description |
| Test coverage | PR touches at least one `test_*.py` file |
| Bounded scope | ≤ 3 substantive changed files, ≥ 1 test file, ≤ 2 non-test files |
| Ignored paths | Docs, README, changelog, images, and `.github/` edits excluded from scope count |
| Merge cutoff | PR merged **before** 2025-01-01 UTC |

### Why the 2025-01-01 cutoff?

`MERGE_CUTOFF` in `filters.py` is `2025-01-01T00:00:00Z`. Rationale:

1. **Training-data leakage.** Issues merged in 2025+ are more likely to appear verbatim in
   public model training corpora and in SWE-bench-style fine-tuning sets.
2. **Stable ground truth.** Older merges have settled test suites; recent merges may still
   be in flux on `main`.
3. **Reproducibility.** The cutoff is a hard datetime check on `merged_at`, not a moving
   window, so the same JSONL file always yields the same task set.

The builder additionally searches merged PRs with `merged:<=2024-12-31` when scanning
GitHub search results.

## Contamination detection

Each task's `issue_body` is embedded with `all-MiniLM-L6-v2` and compared via cosine
similarity against pre-computed SWE-bench Lite train embeddings
(`data/contamination/swebench_train_embeddings.npz`).

- **Threshold:** similarity > **0.85** ⇒ `is_contaminated = True`
- **Policy:** contaminated tasks are **never dropped** from eval runs; they are flagged
  and reported separately (`n_contaminated`, `contamination_rate`, clean-subset means).

See [contamination_analysis.md](contamination_analysis.md) for embedding provenance and
empirical overlap rates on `seed_50`.

## Rubric weights

Composite score is a weighted sum defined in `src/coding_eval/rubric/scorer.py`:

| Axis | Weight | Rationale |
| --- | ---: | --- |
| `test_pass_rate` | 0.35 | Primary correctness signal — does the patch make tests pass? |
| `semantic_score` | 0.20 | LLM judge catches correct-looking diffs that miss the issue intent |
| `diff_minimality` | 0.15 | Penalises shotgun refactors; rewards surgical fixes |
| `complexity_delta` | 0.15 | Penalises unnecessary cyclomatic complexity growth |
| `style_score` | 0.15 | Penalises new ruff violations in added lines |

**Why test_pass dominates:** SWE-bench and related benchmarks treat pass/fail as the
primary metric ([Jimenez et al., ICLR 2024](https://arxiv.org/abs/2310.06770)). We keep
that signal largest while still rewarding patch quality on the other axes.

**Why semantic is second among non-test axes:** Test pass alone cannot detect test-only
cheating or partial fixes; the judge receives pytest output tail and issue context.

Changing weights requires updating `WEIGHTS` in `scorer.py` **and** this document plus
[rubric_design.md](rubric_design.md).

## Provider-agnostic single-shot pipeline

As of v0.2, the single-shot solve loop (gather context → completion → extract patch →
format-fixup reprompt → apply-check + py-compile → bounded retry) lives in
`agents/_solver.py` and is shared by all single-shot adapters (`claude-code`, `openai`).
Each adapter supplies only a `complete(messages) -> (text, incremental_cost_usd)` closure;
the solver is otherwise identical for both providers.

This design means **per-provider score differences are attributable to the model, not the
harness**: both providers see the same prompt, the same retry budget, and the same
validation gates. Cost is accumulated in the solver from the incremental cost each closure
returns; neither adapter can skew total cost by double-counting.

## Judge model

| Role | Model | Temperature |
| --- | --- | ---: |
| Agent adapter (`claude-code`, `claude-code-agentic`) | `claude-sonnet-4-5-20250929` | 0 |
| Agent adapter (`openai`) | `gpt-4o-2024-11-20` | 0 |
| Semantic judge | `claude-sonnet-4-5-20250929` | 0 |

Pinned in `src/coding_eval/models.py`. Judge prompts and parse hardening live in
`src/coding_eval/rubric/semantic.py` (cache version `v6`).

### Limitations

1. **Same-model bias.** Agent and judge share a model family; the judge may favour
   stylistically similar patches.
2. **Non-determinism.** The irreducible source of run-to-run variance is the **agent
   adapter call**: `temperature=0` reduces but does not eliminate sampling variation, and
   the Anthropic API exposes no seed parameter, so the same task can yield a different patch
   on a re-run (observed: a single task swinging ~0.2 composite between runs purely from a
   different generated patch). Everything *downstream* of the patch is deterministic — patch
   extraction, sandbox execution, and the four non-LLM axes are pure functions of the patch,
   and the semantic judge is cached by `(issue, patch prefix, test_pass_rate)` hash so an
   identical patch always scores identically. For stable cross-agent rankings, average over
   N runs rather than treating a single run as ground truth; per-task composite differences
   under ~0.2 are within this noise floor.
3. **Parse failures.** Malformed judge JSON falls back to regex extraction, then a single
   reprompt; persistent failures score `0.0` and log `semantic.parse_failed`.
4. **No execution in judge.** The judge sees patch text and pytest tail, not interactive
   debugging; it cannot verify runtime behaviour beyond reported test output.
5. **Cost.** Each unscored task incurs an Anthropic API call; budget accordingly for full
   50-task runs.

## Execution environment

Every task runs in a **fresh Docker container** (`Dockerfile.sandbox`):

- `--network=none`, `--memory=512m`, `--cpus=1.0`
- Read-only root except `/workspace`; `tmpfs` on `/tmp`
- 120 s hard timeout per container
- Agent API calls happen on the **host**; only the patch string enters the sandbox

## Reproducibility checklist

| Knob | Default | Location |
| --- | --- | --- |
| Task seed shuffle | `42` | `--seed` on `coding-eval run` |
| Task file | `data/tasks/seed_50.jsonl` | `--tasks-file` |
| Embeddings | `data/contamination/swebench_train_embeddings.npz` | `--embeddings-file` |
| Judge temperature | `0` | `semantic.py` |
| Semantic cache | `results/semantic_cache.sqlite` | per run output dir |

## Related docs

- [Rubric design](rubric_design.md) — per-axis formulas
- [Contamination analysis](contamination_analysis.md) — threshold and overlap stats
- [Adding agents](adding_agents.md) — register a new adapter
