# Acceptance — v0.2 "Second agent adapter + hardening"

**Project:** coding-agent-eval-harness · **Branch:** `feat/openai-adapter-and-hardening`
**Input:** "review the project and enhance it if need" (open-ended) · **Mode:** in-place
enhancement of an existing green codebase, no regressions.

This is produced by the AI Project Agency after the plan loop (PASS 98/100), the build &
verify loop (SOLID after one FIX round), security audit, and docs. Every result below was
run offline — no paid API calls, no Docker build, no network — per [ASSUMPTIONS.md](ASSUMPTIONS.md).

---

## Verdict per success criterion (PLAN.md S1–S15)

| # | Criterion | Result | Evidence |
|---|---|:---:|---|
| S1 | Full suite green, no `utcnow` deprecation, ≥ 173+6 tests | ✅ PASS | `196 passed, 1 deselected`; `-W error::DeprecationWarning` clean; +23 new tests |
| S2 | Coverage ≥ 85% | ✅ PASS | `93.15%` |
| S3 | `ruff check .` clean | ✅ PASS | `All checks passed!` |
| S4 | `ruff format --check` clean | ✅ PASS | `70 files already formatted` |
| S5 | `mypy --strict src` clean | ✅ PASS | `Success: no issues found in 44 source files` |
| S6 | `openai` registered + constructible (incl. **no-key**) | ✅ PASS | `get_adapter('openai')` with no `OPENAI_API_KEY` → constructs (lazy client); fixed in FIX round |
| S7 | Key plumbing generalized per-adapter | ✅ PASS | `_API_KEY_ENV`; sentinel test confirms openai↔`OPENAI_API_KEY`, claude↔`ANTHROPIC_API_KEY` (not crossed) |
| S8 | Existing Claude adapter behavior unchanged | ✅ PASS | `test_claude_code/ _agentic/ _agent_retry` pass; `git diff main…HEAD` on those tests empty |
| S9 | New adapter unit tests (happy/retry/exhausted/format/empty) | ✅ PASS | `tests/test_openai_adapter.py` (14) + `tests/test_openai_client_retry.py` (8) |
| S10 | No vestigial deps (`langsmith`/`tree-sitter`/`datasets` core) | ✅ PASS | removed from deps + src; `datasets` → optional `contamination` extra |
| S11 | tz-aware `created_at`, no deprecated datetime | ✅ PASS | `datetime.now(UTC)`; `tzinfo is not None` |
| S12 | Regression gate protective + deterministic skip | ✅ PASS | `REGRESSION_TOLERANCE = 0.10`; explicit absent-baseline → exit 0 |
| S13 | Lockfile consistent | ✅ PASS | `uv lock --check` clean |
| S14 | Docs updated (README, adding_agents, .env.example) | ✅ PASS | + methodology note on the provider-agnostic solver |
| S15 | Cost accounting correct (single + sum-across-retries) | ✅ PASS | `test_openai_cost_single_call`, `test_openai_cost_sums_across_retries`, `test_claude_code_cost` |

**15 / 15 criteria PASS.**

## Build log (final offline sweep)

```
uv run pytest -q            → 196 passed, 1 deselected   (coverage 93.15% ≥ 85%)
uv run ruff check .         → All checks passed!
uv run ruff format --check  → 70 files already formatted
uv run mypy --strict src    → Success: no issues found in 44 source files
uv lock --check             → resolved clean
get_adapter('openai')       → constructs without a key (error deferred to solve, like Claude)
```

The one deselected test is the pre-existing `@pytest.mark.sandbox` Docker test, excluded from
the offline suite by design (unchanged from baseline).

## Security

[SECURITY.md](SECURITY.md): **0 Critical / 0 High.** M-1 (a dangling `datasets` import the dep
removal introduced) was found by the audit and **fixed** (lazy import + optional extra). M-2
(a harness-level diff-path guard) is **accepted defense-in-depth** — the auditor empirically
verified `git apply --check` already rejects `..`/absolute-path traversal at both check and
apply stages and `py_compile` does not execute code, so the host-side patch boundary is
contained. Tracked as future hardening, not a release blocker.

## What was built

- **`openai` agent adapter** (`src/coding_eval/agents/openai_adapter.py`) — single-shot,
  gpt-4o, lazy client construction; registered in `AGENT_REGISTRY`.
- **Shared single-shot solver** (`src/coding_eval/agents/_solver.py`) — the apply-check +
  format-fixup + bounded-retry loop, lifted out of the Claude adapter and now used by both
  single-shot adapters; parameterized over a provider `complete(messages) -> (text,
  incremental_cost_usd)` closure with the solver owning cost accumulation.
- **OpenAI client helpers** (`src/coding_eval/agents/_openai_client.py`) — completion +
  retry/backoff over OpenAI transient errors, empty-`choices` guard, usage→cost pricing.
- **Generalized key plumbing** (`agents/__init__.py`) — `_API_KEY_ENV` map; each adapter
  resolves its own env var; `cli.py` simplified to `get_adapter(agent_id)`.
- **Hardening** — tz-aware `created_at`; `REGRESSION_TOLERANCE` 0.60 → 0.10; removed
  `langsmith`/`tree-sitter`/`datasets` (datasets → optional `contamination` extra + lazy
  import); `openai` 1.53.0 → 1.57.4 (httpx `proxies` fix); removed dead `ANN101` ruff ignore.
- **Tests + CI** — +23 tests; new modules at 100% coverage; CI gains `uv lock --check` and a
  corrected regression-tolerance comment.
- **Docs** — README agents table + honest leaderboard framing, `docs/adding_agents.md` worked
  example, methodology note, `.env.example`; plus several pre-existing doc inaccuracies fixed.

## Deferred (documented, not done)

- **D1. Dataset 20 → 50 tasks** — needs `GITHUB_TOKEN` + network; data-gathering, not code. The
  pipeline is already wired.
- **D2. `claude-code-agentic` in the nightly workflow** — recurring API spend (~$1–2/task);
  needs explicit approval (guardrail).
- **D3. Real OpenAI leaderboard numbers** — needs `OPENAI_API_KEY` + a run.

## Recommended next steps

1. Run `--agents openai` against the dataset with an `OPENAI_API_KEY` to produce the first real
   cross-agent leaderboard row (closes D3).
2. Expand `seed_50` to its namesake 50 tasks (closes D1) — the harness is ready.
3. Optional: add the M-2 diff-path guard in `_validate_patch` (not the fragile `extract.py`).
4. Optional: set an explicit OpenAI request timeout (SECURITY.md L-1).
