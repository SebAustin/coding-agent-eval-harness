# CODEBASE.md — coding-agent-eval-harness

> Analysis date: 2026-06-20. Written by the codebase-onboarding agent; read-only analysis, no source changes.

---

## 1. Overview

`coding-agent-eval-harness` is a reproducible, contamination-aware evaluation framework for
coding agents. It takes a dataset of real GitHub PR-issue pairs, runs one or more agent
adapters that produce unified-diff patches, executes those patches inside a network-isolated
Docker sandbox, and scores every patch on a 5-axis rubric. Results are aggregated into a
leaderboard committed to the repo.

The key design decisions that distinguish it from SWE-bench:

- **Contamination gating** — every task is checked against SWE-bench train embeddings before
  it is scored; contaminated tasks are flagged and excluded from clean counts.
- **5-axis rubric** — rewards surgical, correct diffs rather than just test pass/fail.
- **Reproducible by construction** — pinned base commits, sealed Docker sandbox
  (`--network none --memory 512m`), and a committed `results/leaderboard.json`.

---

## 2. Stack and Tooling

| Layer | Choice | Pinned version |
|---|---|---|
| Language | Python | 3.12.x (requires `>=3.12,<3.13`) |
| Package manager | uv | any recent; lockfile `uv.lock` present |
| Build backend | hatchling | — |
| CLI framework | typer | 0.15.1 |
| Agent API | anthropic | 0.40.0 |
| Validation / schema | pydantic | 2.9.2 |
| Embeddings / contamination | sentence-transformers | 3.3.1 (model: `all-MiniLM-L6-v2`) |
| Complexity scoring | radon | 6.0.1 |
| Sandbox runtime | Docker (via docker-py) | 7.1.0 |
| Structured logging | structlog | 24.4.0 |
| Numerical ops | numpy | 2.1.3 |
| Linter | ruff | 0.8.4 |
| Type checker | mypy | 1.13.0 (strict mode) |
| Test framework | pytest | 8.3.4 + pytest-asyncio, pytest-cov, pytest-mock, respx |
| Async test mode | strict (set in pyproject) | — |

**Runtime note**: `sentence-transformers` pulls in `torch 2.12.0` and `transformers 4.57.6`.
First `uv sync` on a cold machine downloads ~2 GB. Subsequent runs use the uv cache.

### Install

```bash
uv sync --all-extras   # installs runtime + dev (ruff, mypy, pytest, etc.)
cp .env.example .env   # fill in ANTHROPIC_API_KEY if running evals
```

---

## 3. Build / Run / Test

### Verified commands

```bash
# Offline unit tests (no Docker, no API keys)
uv run pytest -q                        # 173 tests, 93.14% coverage — PASSES

# Lint (ruff)
uv run ruff check .                     # zero errors (one removed-rule warning)

# Format check
uv run ruff format --check src          # all 41 files already formatted

# Type check
uv run mypy --strict src                # zero issues in 41 source files

# Full Makefile surface
make test                               # → uv run pytest
make lint                               # → uv run ruff check .
make typecheck                          # → uv run mypy src

# Docker sandbox image (requires Docker)
make build-sandbox                      # docker build -f Dockerfile.sandbox ...

# Run eval (requires ANTHROPIC_API_KEY + sandbox image)
uv run coding-eval run --agents claude-code --limit 5 --smoke

# Per-axis head-to-head (requires sandbox + API key)
make eval-compare
```

### Test markers

| Marker | Meaning |
|---|---|
| *(none)* | Offline unit test; runs everywhere |
| `@pytest.mark.sandbox` | Requires Docker + built sandbox image; excluded from `addopts` by default |

The default `pytest.ini_options` sets `addopts = "-m 'not sandbox'"`, so `uv run pytest`
runs only offline tests. The single sandbox test (`tests/test_sandbox.py`) is excluded from
the default run and from coverage measurement.

---

## 4. Green Baseline

**Status: GREEN (offline suite only)**

```
uv run pytest -q

173 passed, 0 failed, 0 errors

Coverage (src/coding_eval, omitting cli.py, agents/*, sandbox/*, dataset/builder.py):
  Total: 93.14% — Required: 85% — PASSED
```

Full coverage breakdown:

| Module | Cover |
|---|---|
| `dataset/contamination.py` | 100% |
| `dataset/schema.py` | 100% |
| `leaderboard/aggregator.py` | 98% |
| `dataset/io.py` | 97% |
| `rubric/_patch_files.py` | 97% |
| `rubric/test_output.py` | 96% |
| `rubric/semantic.py` | 93% |
| `patching/extract.py` | 89% |
| `patching/git_apply.py` | 90% |
| `dataset/filters.py` | 85% |
| `dataset/repos.py` | 74% (lowest in-scope module) |

**Ruff**: 0 errors (1 innocuous warning: `ANN101` rule was removed from ruff 0.8.x; the
ignore entry in `pyproject.toml` has no effect but does not break anything).

**Mypy**: 0 issues.

**What requires Docker/API keys and is NOT in the offline baseline**:
- `tests/test_sandbox.py` — marked `@pytest.mark.sandbox`; skipped by default.
- The `eval.task_*` integration path in `cli.py` — not covered (deliberately omitted from
  coverage by `pyproject.toml`).
- The `semantic.score` Anthropic call — mocked in unit tests via `pytest-mock`.

---

## 5. Architecture and Data Flow

```
data/tasks/seed_50.jsonl          data/contamination/swebench_train_embeddings.npz
        |                                        |
        v                                        v
cli.py: _run_eval_async()
        |
        |-- asyncio.to_thread: clone_repo_at_commit()   (dataset/repos.py)
        |-- asyncio.to_thread: prepare_offline_wheels()  (sandbox/deps.py)
        |-- compute_contamination()                       (dataset/contamination.py)
        |
        |-- adapter.solve(task, repo_path)                (agents/*.py)
        |        returns AgentSolveResult(patch, cost_usd, raw_response)
        |
        |-- check_unified_diff()                          (patching/git_apply.py)
        |-- patch_py_files_compile()                      (patching/validate.py)
        |
        |-- sandbox.run_patch()                           (sandbox/runner.py)
        |        Docker container: git apply + pytest
        |        returns SandboxResult(exit_code, stdout, stderr, ...)
        |
        |-- score_rubric()                                (rubric/scorer.py)
        |        parallel: diff_minimality, complexity, style
        |        serial:   semantic (calls Anthropic judge)
        |        returns RubricScores(5 floats + composite)
        |
        v
aggregate()                       (leaderboard/aggregator.py)
write_leaderboard()               (leaderboard/render.py)
→ results/leaderboard.json
→ results/leaderboard.md
```

### Module-by-module table

| Package / Module | Responsibility | Public interface |
|---|---|---|
| `cli.py` | Entry point for `coding-eval run` and `coding-eval build-dataset` Typer commands | `app` (Typer app) |
| `models.py` | Single source of truth for pinned model IDs | `DEFAULT_AGENT_MODEL`, `DEFAULT_JUDGE_MODEL` |
| `dataset/schema.py` | Pydantic models: `Task` (frozen, `extra="forbid"`) and `TaskResult` | `Task`, `TaskResult` |
| `dataset/io.py` | JSONL read/write for tasks and results | `load_tasks()`, `dump_task_results()` |
| `dataset/contamination.py` | Cosine-similarity check of issue body vs SWE-bench train embeddings | `compute_contamination()`, `batch_check()` |
| `dataset/filters.py` | PR-to-task selection filters (bug label, test coverage, scope, cutoff) | `passes_all_filters()`, `filter_failure_reasons()` |
| `dataset/builder.py` | `GitHubDatasetBuilder` — async GitHub API crawler that applies filters | `GitHubDatasetBuilder.run()` |
| `dataset/repos.py` | Shallow-clone at a pinned commit via GitPython | `clone_repo_at_commit()` |
| `agents/base.py` | `AgentAdapter` ABC: `async solve(task, repo_path) → AgentSolveResult` | `AgentAdapter` |
| `agents/result.py` | Frozen dataclass returned by every adapter | `AgentSolveResult` |
| `agents/__init__.py` | `AGENT_REGISTRY` dict + `get_adapter()` factory | `get_adapter()`, `AGENT_REGISTRY` |
| `agents/claude_code.py` | Single-shot adapter: gather context → one completion → extract/retry patch | `ClaudeCodeAdapter` |
| `agents/claude_code_agentic.py` | Tool-using adapter: read_file/grep/list_dir loop, forced-diff turns, cost ceiling | `ClaudeCodeAgenticAdapter` |
| `agents/aider.py` | Subprocess wrapper around the `aider` CLI | `AiderAdapter` |
| `agents/context.py` | `gather_repo_context()` — relevance-aware file context builder for single-shot agent | `gather_repo_context()` |
| `agents/repo_tools.py` | `RepoTools` with `dispatch()` for agentic adapter; TOOL_SPECS dicts | `RepoTools`, `TOOL_SPECS` |
| `agents/_common.py` | Shared retry/cost utilities used by both Claude adapters | `create_message_with_retry()`, `usage_cost_usd()` |
| `agents/prompts.py` | System prompt and reprompt constants | `SYSTEM_PROMPT`, `FORMAT_REPROMPT`, etc. |
| `patching/extract.py` | Extract a unified diff from free-form model output; recount miscounted hunk headers | `extract_unified_patch()`, `looks_like_diff_attempt()` |
| `patching/git_apply.py` | Dry-run `git apply --check` and actual apply | `check_unified_diff()`, `apply_unified_diff()` |
| `patching/validate.py` | Python compile-check of patched files | `patch_py_files_compile()` |
| `rubric/scorer.py` | Orchestrates 5-axis scoring; returns `RubricScores` with `.composite` | `score()`, `RubricScores`, `WEIGHTS` |
| `rubric/diff_minimality.py` | `1 - min(changed_lines/200, 1.0)` | `score()` |
| `rubric/complexity.py` | Radon cyclomatic complexity before vs after patch | `score()` |
| `rubric/style.py` | Ruff violations introduced in changed lines (subprocess) | `score()` |
| `rubric/semantic.py` | Anthropic judge (Claude Sonnet 4.5, temp=0) with SQLite cache and reprompt fallback | `score()` |
| `rubric/test_pass.py` | Thin wrapper calling `sandbox/patch.py` | `score()` |
| `rubric/_patch_files.py` | Extract changed Python file paths; detect test-only patches | `changed_py_files()`, `patch_only_modifies_tests()` |
| `rubric/test_output.py` | Parse pytest stdout for pass counts, syntax errors, target-test failures | helpers |
| `sandbox/runner.py` | `DockerSandbox.run_patch()` — git apply + pytest in a sealed container | `DockerSandbox`, `SandboxResult` |
| `sandbox/deps.py` | Download and cache manylinux wheels for repo deps; copy into sandbox | `prepare_offline_wheels()` |
| `sandbox/images.py` | `DEFAULT_SANDBOX_IMAGE` constant | — |
| `sandbox/patch.py` | Parse SandboxResult → test pass rate | `compute_test_pass_rate()` |
| `leaderboard/aggregator.py` | Aggregate `TaskResult` list into `Leaderboard` / `LeaderboardEntry` | `aggregate()` |
| `leaderboard/render.py` | Write JSON + Markdown; rich table to stdout | `write_leaderboard()`, `print_leaderboard_table()` |

### Trust boundaries

- **Host process** — agent adapters run here; they have read access to the cloned repo
  only via `RepoTools._resolve()` (path-escape guard). Agents never write to the repo;
  patches are strings in memory.
- **Docker sandbox** — `--network none`, `--memory 512m`, `--nano-cpus 1e9`. The only
  communication channel is the mounted tmpdir (copied from the repo checkout). Container is
  force-removed after each run.
- **Anthropic API** — called from host for agent completions (claude_code / claude_code_agentic)
  and for the semantic judge. Protected by `create_message_with_retry()` with exponential
  backoff. API key is `ANTHROPIC_API_KEY` env var; never logged.

---

## 6. Conventions

### Code style

- **All source** in `src/coding_eval/` uses `from __future__ import annotations`, Pydantic
  `ConfigDict(frozen=True, extra="forbid")` on public models, and `dataclass(frozen=True,
  slots=True)` for internal value objects.
- **Immutability first**: `Task` and `RubricScores` are immutable; `TaskResult` and
  `LeaderboardEntry` are also frozen pydantic models.
- **No mutation of external state** from rubric modules — each uses a fresh `tempfile.mkdtemp`
  copy of the repo that is removed in a `finally` block.
- `__all__` is declared in every module.
- `from __future__ import annotations` defers evaluation everywhere (required for forward refs
  in TYPE_CHECKING blocks).
- Type annotations are exhaustive; `mypy --strict` passes with zero issues.

### Naming

- Agent IDs are kebab-case strings (registry keys): `claude-code`, `claude-code-agentic`,
  `aider`.
- Module-level loggers are `structlog.get_logger(__name__)`.
- Rubric scoring functions are always `score(...)` in their module.

### Error handling

- `RepoCloneError` from `dataset/repos.py` is the only domain exception; it propagates to
  `_eval_task()` where it is caught and written to `TaskResult.error`.
- `BLE001` (broad exception) is explicitly suppressed in `src/coding_eval/**/*.py` for the
  outer eval loop — intentional design.
- Docker and API errors in the sandbox/runner are caught narrowly and returned as failed
  `SandboxResult`.

### Commits / branch norms

- Conventional commits format: `type: description`, types: `feat`, `fix`, `chore`, `docs`,
  `ci`, `perf`, `refactor`, `test`.
- Leaderboard update commits use `[skip ci]` to avoid CI loops.
- The nightly workflow auto-commits `results/leaderboard.json` + `results/leaderboard.md`
  with `chore(leaderboard): nightly eval update [skip ci]`.

### Pytest layout

- `tests/conftest.py` provides only `fixtures_dir: Path` fixture.
- Test files map to source modules (e.g. `test_contamination.py` → `dataset/contamination.py`).
- Async tests use `@pytest.mark.asyncio` and the `asyncio_mode = "strict"` setting.
- Fixtures: `tests/fixtures/` contains sample diffs (`good.diff`, `sample_patch.diff`) and
  `tasks_10.jsonl` (10 tasks for integration tests).

---

## 7. Tests

| Test file | Tests | What it covers |
|---|---|---|
| `test_rubric.py` | 38 | All 5 rubric axes: diff_minimality, complexity, style, test_pass, semantic (mocked judge) |
| `test_patch_extract.py` | 19 | `patching/extract.py` — diff extraction from fenced / raw model output |
| `test_contamination.py` | 17 | Cosine-sim contamination check, batch, edge cases |
| `test_sandbox_deps.py` | 13 | Wheel cache helpers, poetry parsing |
| `test_repo_tools.py` | 16 | `RepoTools` path-escape guard, read_file/grep/list_dir |
| `test_agent_context.py` | 11 | `gather_repo_context`, keyword extraction, relevance windowing |
| `test_filters.py` | 8 | PR filter pipeline |
| `test_aggregator.py` | 7 | Leaderboard aggregation |
| `test_dataset.py` | 9 | Task schema, IO round-trips |
| `test_claude_code_agentic.py` | 6 | Agentic adapter with mocked API |
| `test_claude_code.py` | 5 | Single-shot adapter with mocked API |
| `test_patch.py` | 6 | Hunk-count tolerances |
| `test_git_apply.py` | 4 | `check_unified_diff` / `apply_unified_diff` on real git repos |
| `test_repos.py` | 3 | `clone_repo_at_commit` with mock git |
| `test_agent_retry.py` | 3 | Exponential-backoff retry logic |
| `test_io.py` | 2 | JSONL load/dump |
| `test_run.py` | 2 | CLI `_eval_task` happy-path with mocks |
| `test_patch_validate.py` | 2 | `patch_py_files_compile` |
| `test_builder_edges.py` | 2 | `GitHubDatasetBuilder` edge cases |
| `test_sandbox.py` | 1 | `@pytest.mark.sandbox` — Docker integration (skipped offline) |

**Coverage gaps** (outside the measured scope but worth noting):
- `cli.py` — excluded from coverage, no unit tests; the Typer command wiring is tested only
  by the CI smoke-eval job.
- `agents/*` — excluded from coverage; individual adapters have unit tests but the full
  `ClaudeCodeAdapter.solve()` happy-path is only exercised end-to-end in `eval-compare`.
- `sandbox/runner.py` and `sandbox/deps.py` — excluded from coverage; the sandbox test is
  Docker-gated.
- `dataset/builder.py` — excluded from coverage; requires GITHUB_TOKEN.

---

## 8. Dependencies and Risk

### Notable dependencies

| Dep | Notes |
|---|---|
| `anthropic==0.40.0` | Hard-pinned. The agentic adapter uses `tool_use` message blocks. Any bump risks a breaking API change in how tool results are structured. |
| `sentence-transformers==3.3.1` | Pulls in `torch 2.12.0` and `transformers 4.57.6` — the two largest transitive deps (~2 GB). Only used for contamination checking; not on the hot path during eval. |
| `docker==7.1.0` | Docker SDK for Python; requires a running daemon to do anything useful. |
| `langsmith==0.2.10` | Listed as a dependency but not used in any source file that was found — possibly vestigial. |
| `datasets==3.2.0` | Similarly imported nowhere in the current source; appears to be a future-facing placeholder. |
| `tree-sitter==0.23.0` | Imported in no current source file; appears vestigial (may have been planned for AST-based complexity). |
| `openai==1.53.0` | No OpenAI adapter exists yet; imported nowhere. Placeholder for the Codex adapter mentioned in README issue #2. |

### License

Apache-2.0 for this repo. Target repos (`Textualize/rich`, `fastapi/typer`) are MIT;
the harness only clones them at evaluation time, so no license embedding occurs.

### Vulnerability surface

- No web-exposed endpoints; all network activity is outbound (GitHub clones, Anthropic API).
- Docker sandbox uses `--network none` — no container egress.
- `ANTHROPIC_API_KEY` is env-only; `.env.example` shows the pattern, no secret committed.
- No `requirements.txt` with unpinned deps; `uv.lock` provides full reproducibility.

---

## 9. Tech Debt and Issues

1. **`seed_50.jsonl` has only 20 tasks, not 50** — the file is named `seed_50` but contains
   exactly 20 lines. The README's "pending" issue #2 is dataset expansion to 50 tasks.
   Running `make eval` produces results labeled `seed_50` with `n_total=20`.

2. **`leaderboard.json` shows all-zero scores for both agents** — the current committed
   `results/leaderboard.json` has `mean_composite_score: 0.0` and `n_errors: 20` for both
   `claude-code` and `aider`. This appears to be from a run where either the API key was
   absent or the Docker sandbox was not available. The leaderboard in the README is from a
   different (earlier) run. This is not a code bug but a data state issue.

3. **Vestigial dependencies** — `langsmith`, `datasets`, `tree-sitter`, and `openai` are in
   `pyproject.toml` but used by nothing in the current source. They add install time and
   attack surface. `tree-sitter` in particular installs a Rust-compiled binary.

4. **Ruff `ANN101` warning** — the rule was removed from ruff 0.8.x. The ignore entry in
   `pyproject.toml:tool.ruff.lint.ignore` is now a no-op warning. Low risk, minor noise.

5. **`datetime.utcnow()` deprecation warning** — `TaskResult.created_at` uses
   `Field(default_factory=datetime.utcnow)` which emits a DeprecationWarning in Python 3.12.
   Should be `datetime.now(UTC)`.

6. **`AiderAdapter` does not pass the issue title** — `aider.py` line 22 does
   `_ = task.issue_title` (intentionally discards it). The aider subprocess receives only
   the issue body in `--message`. This reduces aider's context vs the claude adapters.

7. **Nightly workflow only runs `claude-code` + `aider`** — `claude-code-agentic` is not in
   the nightly eval despite being a first-class registered adapter. Its numbers are not
   tracked continuously.

8. **Regression gate tolerance is 0.60** — `ci_regression_gate.py` allows the composite to
   drop by up to 0.60 before failing. Since the current maximum composite is ~0.60, this
   gate would only fire if every task scored zero. Effectively no regression protection.

9. **`context.py` keyword-extraction stopword list** is hand-curated and fairly large; adding
   domain-specific repos may require extending it to avoid surfacing noise terms.

10. **`patching/extract.py` hunk recount tolerance** (`HUNK_COUNT_TOLERANCE = 1`) — models
    routinely miscount hunk lengths by exactly 1 line. The extractor corrects this
    silently. If a model produces a diff that is wrong by more than 1 line, the correction
    fails and the patch is rejected.

---

## 10. Extension Points

### Adding a new agent adapter

1. Create `src/coding_eval/agents/{name}.py` implementing `AgentAdapter` (ABC from `base.py`).
2. Register in `AGENT_REGISTRY` in `agents/__init__.py`.
3. If the constructor takes `api_key`, add the id to `_API_KEY_AGENTS` in the same file.
4. Add unit tests following `test_claude_code.py` / `test_claude_code_agentic.py` pattern.
5. Add the agent id to `leaderboard-nightly.yml` after verifying locally with `--limit 5`.

The `ClaudeCodeAgenticAdapter` is the reference for tool-using agents. The `RepoTools` class
in `repo_tools.py` can be extended with new read-only tools by adding entries to both the
class methods and `TOOL_SPECS` list.

**Hook location**: `agents/__init__.py` → `AGENT_REGISTRY` dict.

### Adding a new rubric axis

1. Create `src/coding_eval/rubric/{axis_name}.py` with a `score(...)` function returning
   `float` in `[0.0, 1.0]`.
2. Add to `WEIGHTS` dict in `rubric/scorer.py` (re-normalize weights to sum to 1.0).
3. Call from `rubric/scorer.py:score()` — parallel axes go in the `asyncio.gather()` call;
   judge-dependent axes go after.
4. Add the field to `RubricScores` dataclass and to `TaskResult` / `LeaderboardEntry` models.
5. Update `leaderboard/render.py` column headers and `leaderboard/aggregator.py` mean
   calculation.

**Risky touch**: `TaskResult` and `LeaderboardEntry` use `extra="forbid"`. Adding a field to
`RubricScores` without also adding it to both Pydantic models will raise a `ValidationError`
at runtime.

### Expanding the dataset

- Add repos to `data/tasks/seed_50.jsonl` manually (following the `Task` schema) or run:
  ```bash
  uv run coding-eval build-dataset --repo owner/repo --limit 50 --output data/tasks/seed_50.jsonl
  ```
- The merge cutoff is `2025-01-01` in `dataset/filters.py:MERGE_CUTOFF`. Adjust if needed.
- Task filter knobs: `MAX_SUBSTANTIVE_FILES = 3`, `MAX_NON_TEST_FILES = 2`,
  `MIN_ISSUE_BODY_LEN = 100` (all in `filters.py`).
- After adding tasks, re-run `scripts/precompute_contamination.py` if new tasks come from
  repos that may overlap with SWE-bench train.

**Hook location**: `dataset/filters.py` constants + `dataset/builder.py:GitHubDatasetBuilder`.

### Changing the contamination threshold

`dataset/contamination.py:CONTAMINATION_THRESHOLD = 0.85`. Analysis is in
`docs/contamination_analysis.md`.

### Changing the judge model

`models.py:DEFAULT_JUDGE_MODEL`. The `semantic.py` cache key includes `CACHE_VERSION = "v6"`;
bump that constant when changing the model to invalidate stale cache entries.

### CI regression gate

`scripts/ci_regression_gate.py:REGRESSION_TOLERANCE = 0.60`. Lower this once the leaderboard
stabilizes to get real regression protection.

---

## 11. Remote Feature Branch: `feat/agentic-adapter-multi-file`

```
git log origin/feat/agentic-adapter-multi-file --oneline -20
```

This branch has been **merged to main** (PR #3, commit `3bb7a54`). Its remaining delta vs
current `main` is only 2 files, 37 lines:

```
README.md                  |  8 ++++----
docs/agentic_comparison.md | 39 +++++++++++++++++++++++++++++++++------
```

These are documentation-only updates adding measured results from the agentic adapter
head-to-head (+0.128 composite improvement on the completed tasks subset). No code changes
remain unmerged on that branch.

---

## 12. Candidate Enhancements (not implemented, ranked by value / risk)

| Rank | Enhancement | Value | Risk / Effort |
|---|---|---|---|
| 1 | **Fix `datetime.utcnow()` deprecation + tighten regression gate** | Low noise + actual regression protection | Very low — 2-line fix in `schema.py`; adjust `REGRESSION_TOLERANCE` in `ci_regression_gate.py`. No model changes. |
| 2 | **Expand dataset from 20 to 50 real tasks** (README issue #2) | Core benchmark validity; confidence interval on scores narrows significantly | Medium — requires `GITHUB_TOKEN`, re-running `build-dataset`, verifying all 50 clones succeed, re-running the nightly eval. |
| 3 | **Add OpenAI Codex / GPT-4o adapter** (README issue #1) | Multi-agent comparison; `openai==1.53.0` is already installed | Medium — implement `OpenAIAdapter` in `agents/openai_codex.py`, register, add to `_API_KEY_AGENTS` with `OPENAI_API_KEY`. Need to handle OpenAI's message format vs Anthropic's. |
| 4 | **Add `claude-code-agentic` to nightly eval workflow** | Track agentic-vs-single-shot scores continuously instead of one-shot runs | Low — 2-line change to `leaderboard-nightly.yml`; costs ~$1-2/task vs $0.09 so budget awareness needed. |
| 5 | **Remove vestigial deps** (`langsmith`, `datasets`, `tree-sitter`, `openai` if no adapter added) | Faster cold installs, reduced attack surface | Low — remove from `pyproject.toml`, run `uv sync`, verify tests still pass. Landmine: `openai` may be needed for enhancement #3; only remove if that is not planned. |

### Landmines to know before editing

- `TaskResult` uses `extra="forbid"` — any new field in `RubricScores` must also be added to
  `TaskResult` **and** `LeaderboardEntry` or the run loop will crash at result construction.
- `semantic.py` SQLite cache is keyed by `CACHE_VERSION`. Changing the judge model, system
  prompt, or any calibration logic requires bumping `CACHE_VERSION` to avoid stale scores.
- `_common.py` pricing constants (`INPUT_USD_PER_MTOK = 3.0`, `OUTPUT_USD_PER_MTOK = 15.0`)
  are for Sonnet 4.5. Any model change requires updating both constants and `models.py`.
- `patching/extract.py` has 195 lines of regex + hunk-recount logic. It is the highest-risk
  module to touch — all rubric axes depend on correct patch extraction. It has 89% coverage;
  the 22 missed lines are edge cases in the multi-diff and git-style header normalisation paths.
- `agents/context.py:gather_repo_context()` owns the context-window budget (48 KB total, 12 KB
  per file). Changing these without testing on real large repos will silently degrade single-shot
  agent quality.
- The nightly workflow writes directly to `main` with `contents: write` permission. Be careful
  when touching `leaderboard-nightly.yml` — a misconfigured push step could corrupt history.
