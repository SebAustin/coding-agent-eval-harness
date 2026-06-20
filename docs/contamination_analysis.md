# Contamination analysis

How we detect overlap between eval tasks and SWE-bench training data, why we flag but
never drop contaminated tasks, and how to interpret leaderboard contamination columns.

See also [methodology.md](methodology.md) for the high-level policy and
[data/contamination/README.md](../data/contamination/README.md) for embedding file
provenance.

## Problem

Public coding benchmarks — especially SWE-bench — are widely used for model training and
fine-tuning. An eval task whose issue text closely matches a training instance gives
inflated scores without measuring generalisation. We flag such tasks; we do **not** remove
them from runs.

## Method

| Component | Value |
| --- | --- |
| Embedding model | `all-MiniLM-L6-v2` (384-dim) |
| Corpus | SWE-bench Lite train split embeddings |
| Storage | `data/contamination/swebench_train_embeddings.npz` |
| Query text | Task `issue_body` |
| Similarity | Cosine (L2-normalised vectors) |
| Threshold | **> 0.85** ⇒ `is_contaminated = True` |

Implementation: `src/coding_eval/dataset/contamination.py`.

```python
is_contaminated, max_sim = compute_contamination(issue_body, swebench_embeddings, model)
```

`TaskResult.is_contaminated` and `TaskResult.contamination_similarity` are always populated.

## Embedding corpus

Pre-computed offline via `scripts/precompute_contamination.py`:

- Source dataset: [princeton-nlp/SWE-bench_Lite](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite)
- Embedded text per instance: `{instance_id}\n{problem_statement}`
- Lite has no dedicated `train` split on HuggingFace; we embed `train` when present,
  otherwise `dev` + `test` (documented in `data/contamination/README.md`)

Regenerate after changing the embedding model or corpus:

```bash
uv run python scripts/precompute_contamination.py
```

## Threshold rationale (0.85)

| Consideration | Detail |
| --- | --- |
| Empirical band | MiniLM cosine scores ≥ 0.85 indicate near-paraphrase or copy-paste overlap |
| False positives | Lower thresholds (e.g. 0.75) flag generic bug templates shared across repos |
| False negatives | Higher thresholds miss lightly reworded training instances |
| Stability | Fixed constant `CONTAMINATION_THRESHOLD = 0.85` in code and docs |

The threshold is intentionally conservative: we prefer **flagging** suspicious tasks over
silently treating them as clean.

## seed_50 snapshot

On the current `data/tasks/seed_50.jsonl` corpus (20 tasks built so far; target 50 — see
[issue #2](https://github.com/SebAustin/coding-agent-eval-harness/issues/2)):

| Metric | Value |
| --- | ---: |
| `n_total` | 20 |
| `n_contaminated` | 0 |
| `contamination_rate` | 0% |

Numbers above reflect the live built corpus. Update this table after each dataset expansion run.

Leaderboard output always includes:

- `n_total`, `n_contaminated`, `n_clean`, `contamination_rate` per agent
- Clean-subset means can be computed offline by filtering `is_contaminated == false`

**Policy:** never filter contaminated tasks from eval — report **all** and **clean**
metrics separately in publications.

## Reporting checklist

When publishing leaderboard results, include:

1. Full-corpus composite (all tasks in the run)
2. `n_contaminated` and `contamination_rate`
3. Clean-subset composite (optional but recommended)
4. Embedding model name and threshold
5. Task file hash or git commit for `seed_50.jsonl`

## CI and nightly

- CI smoke eval (`--smoke`, 5 tasks) computes contamination per task but does not gate on it.
- Nightly workflow commits updated `results/leaderboard.json` with contamination columns
  refreshed from the latest full run.

## Related docs

- [Methodology](methodology.md) — merge cutoff and task selection
- [Rubric design](rubric_design.md) — scoring axes (independent of contamination flag)
- [Adding agents](adding_agents.md) — new adapters inherit contamination checks automatically
