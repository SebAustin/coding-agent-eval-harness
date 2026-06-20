# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-06-20

Second agent adapter + harness hardening. The single-shot pipeline is now
provider-agnostic, so cross-agent score differences are attributable to the model
rather than the harness.

### Added
- **`openai` agent adapter** (`gpt-4o`) — a second in-process single-shot adapter,
  registered in `AGENT_REGISTRY` and runnable via `--agents openai`. Delivers on the
  cross-agent leaderboard goal. See [docs/adding_agents.md](docs/adding_agents.md).
- **Shared single-shot solver** (`coding_eval/agents/_solver.py`) — the apply-check +
  format-fixup + bounded-retry loop, lifted out of the Claude adapter and reused by both
  single-shot adapters via a provider `complete(messages) -> (text, incremental_cost_usd)`
  seam (the solver owns cost accumulation).
- **OpenAI client helpers** (`coding_eval/agents/_openai_client.py`) — completion +
  retry/backoff over OpenAI transient errors, empty-`choices` guard, usage→cost pricing.
- Optional `contamination` extra (`pip install '.[contamination]'` / `uv sync --extra
  contamination`) for the precompute-only `datasets` dependency.
- `uv lock --check` step in CI; mandatory cost-accumulation tests; +23 tests overall
  (new modules at 100% coverage).

### Changed
- **Generalized API-key plumbing** — `_API_KEY_ENV` maps each adapter to its env var;
  every adapter resolves its own key (`ANTHROPIC_API_KEY` vs `OPENAI_API_KEY`). The OpenAI
  client is constructed lazily, so the adapter is constructible without a key (a missing
  key surfaces at solve time, matching the Anthropic adapter).
- `ClaudeCodeAdapter` rewritten as a thin closure over the shared solver — behavior
  unchanged (regression-guarded by the existing suite + a new cost assertion).
- `REGRESSION_TOLERANCE` in the CI regression gate lowered `0.60 → 0.10` (0.60 effectively
  never fired).
- Bumped `openai` `1.53.0 → 1.57.4` to fix an `httpx==0.28.1` `proxies` incompatibility
  that made the OpenAI client non-constructible at runtime.

### Removed
- Vestigial dependencies `langsmith`, `tree-sitter`, and `datasets` from the core
  install (`datasets` moved to the optional `contamination` extra). Dropped the dead
  `ANN101` ruff ignore and the stale `datasets` mypy override.

### Fixed
- `TaskResult.created_at` now uses timezone-aware `datetime.now(UTC)` instead of the
  deprecated `datetime.utcnow()`.
- Documentation accuracy: architecture diagram adapter names, dataset task count
  (20, not 50), and a `CACHE_VERSION` doc/source drift.

### Security
- STRIDE review in [SECURITY.md](SECURITY.md): 0 Critical / 0 High. Host-side patch
  boundary (`git apply --check` + `py_compile`) empirically confirmed to contain path
  traversal and non-execution. A harness-level diff-path guard is tracked as accepted
  defense-in-depth.

### Deferred
- Dataset expansion 20 → 50 tasks (needs `GITHUB_TOKEN`); `claude-code-agentic` in the
  nightly workflow (recurring spend); real OpenAI leaderboard numbers (needs
  `OPENAI_API_KEY` + a run).

## [0.1.0]

Initial release: reproducible, contamination-aware eval harness for coding agents —
50-task seed set (currently 20 built), Docker-isolated execution, 5-axis rubric scoring,
and a committable cross-agent leaderboard, with the `claude-code` and
`claude-code-agentic` adapters.

[0.2.0]: https://github.com/SebAustin/coding-agent-eval-harness/releases/tag/v0.2.0
[0.1.0]: https://github.com/SebAustin/coding-agent-eval-harness/releases/tag/v0.1.0
