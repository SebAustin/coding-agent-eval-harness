# Assumptions — v0.2 enhancement (AI Project Agency)

The request was open-ended ("review the project and enhance it if need"). The agency
onboarded the codebase ([CODEBASE.md](CODEBASE.md)), confirmed a **green baseline**
(`173 passed, 93.14% coverage, ruff + mypy --strict clean`), and selected an enhancement
scope. Decisions and assumptions are logged here per the agency guardrails.

## Scope selected

**v0.2 — "Second agent adapter + hardening".** Chosen because the project's headline value
is a *cross-agent* leaderboard, but only Claude has a real in-process adapter, and the README
flags multi-agent comparison as pending work.

1. **OpenAI agent adapter** — a new `AgentAdapter` using the already-declared `openai==1.53.0`
   dependency, single-shot, reusing the existing apply-check + format-fixup solve loop via a
   shared solver (DRY). Registered in `AGENT_REGISTRY`; `OPENAI_API_KEY` handled like the
   Anthropic key. Fully unit-tested with a **mocked** OpenAI client (no network), mirroring
   `tests/test_claude_code.py`, so it stays in the offline green baseline.
2. **Hardening** — fix `datetime.utcnow()` deprecation (timezone-aware); make
   `scripts/ci_regression_gate.py` tolerance actually protective + documented; remove
   vestigial deps (`langsmith`, `datasets`, `tree-sitter`) and their mypy overrides.
3. **Docs + acceptance** — README agents table, `docs/adding_agents.md`, `.env.example`,
   `ACCEPTANCE.md`.

## Assumptions

- **A1. Default OpenAI model.** The adapter pins a current, widely-available chat model
  (`gpt-4o`, dated snapshot) with an env override, mirroring how `models.py` pins the
  Anthropic snapshot. Exact id is swappable; reproducibility comes from pinning, not the
  specific choice.
- **A2. Offline-testable is the bar.** Like the existing Claude adapters, the OpenAI adapter
  is validated via mocked-client unit tests. Running it against real tasks needs
  `OPENAI_API_KEY` and is out of scope for the green baseline (documented in acceptance).
- **A3. No real API spend.** The agency will not call paid OpenAI/Anthropic endpoints or build
  the Docker image during this work; verification relies on the offline suite + mocks.
- **A4. Cost rates.** OpenAI pricing constants are added alongside the Anthropic ones; if the
  default model changes, the rates must change with it (documented next to the constants).

## Deferred (documented, not done — would need an explicit go / external resources)

- **D1. Dataset 20 → 50 tasks** (README issue noted): requires `GITHUB_TOKEN` and network to
  re-run `build-dataset`; it is a data-gathering task, not a code change. The pipeline is
  already wired for it.
- **D2. Add `claude-code-agentic` to the nightly workflow**: introduces recurring API spend
  (~$1–2/task) on a schedule — a money-spending change that needs explicit approval per the
  guardrails.
- **D3. Real cross-agent leaderboard numbers for OpenAI**: needs `OPENAI_API_KEY` + a run.

## Build-time amendments

- **openai pin raised 1.53.0 → 1.57.4.** The planning docs assumed `openai==1.53.0` (already
  declared in pyproject), but `openai==1.53.0` has an `httpx` `proxies` incompatibility with
  the `httpx==0.28.1` already pinned in the project. The dep was bumped to `1.57.4` during the
  build to resolve this; the lock file is consistent (`uv lock --check` passes). The adapter
  uses only long-stable SDK surface (see SECURITY.md §3.2). PLAN.md references to "1.53.0"
  reflect the pre-build plan and were not retroactively edited.

## Guardrails honored

- Work happens on feature branch `feat/openai-adapter-and-hardening` (never `main`).
- No secrets committed; keys via env + `.env.example` placeholders.
- Existing tests must keep passing (regression guard); no behavior change to existing adapters.
- No production deploys, no pushing to remotes, nothing that spends money — without an explicit go.
