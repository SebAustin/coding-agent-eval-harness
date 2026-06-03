# SWE-bench contamination embeddings

Pre-computed L2-normalized sentence embeddings for the **SWE-bench Lite train** split,
used to flag eval tasks that overlap training data.

## File

| Path | Description |
|------|-------------|
| `swebench_train_embeddings.npz` | NumPy archive with key `embeddings`, shape `(N, 384)` |

- **Model:** `all-MiniLM-L6-v2` (384-dim)
- **Source:** [princeton-nlp/SWE-bench_Lite](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite)
- **Splits embedded:** `train` when present; otherwise `dev` + `test` (Lite has no `train` split on HuggingFace)
- **Text embedded:** `{instance_id}\n{problem_statement}` per instance

## Generate

```bash
uv sync
uv run python scripts/precompute_contamination.py
```

Optional flags: `--output`, `--batch-size`.

Requires network access to Hugging Face on first run.

## Detection

`coding_eval.dataset.contamination.compute_contamination` embeds a task `issue_body`,
computes max cosine similarity against this corpus, and sets `is_contaminated=True`
when similarity **> 0.85**.

Always report `n_total`, `n_contaminated`, and `contamination_rate` in leaderboard
output; never drop contaminated tasks from eval runs.
