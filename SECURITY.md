# SECURITY.md — coding-agent-eval-harness

> Security audit of the v0.2 enhancement on branch `feat/openai-adapter-and-hardening`
> (OpenAI adapter + shared solver + hardening). Produced with the `threat-model` (STRIDE)
> skill. Audit date: 2026-06-20. Method: read-only static review of the branch diff
> (`main...HEAD`) plus non-destructive scans and empirical `git apply` containment tests.
> No source was modified.
>
> **Scope note (smart-contract-audit skill):** evaluated for applicability and found
> **not applicable** — this is a Python evaluation harness with no blockchain/web3 / EVM /
> Solidity / wallet / on-chain signing component. No `.sol` files, no transaction-signing
> code, no private-key/seed-phrase handling. That skill is therefore recorded as N/A rather
> than skipped silently.

---

## 0. Verdict

**Overall posture: SOLID with two low-risk follow-ups.** No CRITICAL or HIGH findings in the
enhancement or the touched areas. The new external-API surface (OpenAI adapter) sits on the
same outbound-HTTPS trust boundary as the existing Anthropic call, keys are env-only and never
logged, and the host-side patch boundary (apply-check + py-compile) is non-mutating /
non-executing and is contained by `git apply`'s own path checks (verified empirically).

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 2 |
| Low | 3 |
| Informational | 3 |

**Must-fix before "SOLID" is declared:** none are blocking. The two MEDIUMs (M-1 dangling
`datasets` import in a precompute script; M-2 no harness-level defense-in-depth on diff target
paths) are recommended hardening, not release blockers. M-1 is a functional break in an
offline utility script and should be fixed in this PR for hygiene.

Offline baseline re-verified during the audit: `uv run pytest` exits 0, coverage 93.15%
(>= 85% gate), `datetime.utcnow` removed from `src`, `uv lock --check` resolves cleanly.

---

## 1. System decomposition

### 1.1 Trust boundaries

| Boundary | Description | What crosses it |
|---|---|---|
| **External — model providers** | Outbound HTTPS to Anthropic API and (NEW) OpenAI API | Prompt out (issue text + repo file slices); completion in (free-form text → patch). API keys travel in the `Authorization` header (SDK-managed, TLS). |
| **External — source repos / dataset** | GitHub clone of target repos at a pinned commit; task JSONL on disk | Untrusted issue text (`issue_title`, `issue_body`) and untrusted repo file contents flow INTO the prompt. |
| **Host process** | `cli.py` → `get_adapter` → adapter `.solve` → `_solver.solve_single_shot` → `patching.*` | Model output (a patch string) is `git apply --check`'d and (in a temp copy) applied + `py_compile`'d **on the host**. This is the boundary the enhancement most affects. |
| **Docker sandbox** | `--network none`, `--memory 512m`, `--nano-cpus 1e9`, force-removed per run | The patch is applied and tests are EXECUTED only here. Patch generation + validation happen on the host, before this boundary. |

### 1.2 Entry points (this enhancement)

- `OpenAIAdapter.solve()` (`src/coding_eval/agents/openai_adapter.py`) — new provider closure
  calling `client.chat.completions.create`.
- `create_completion_with_retry` (`src/coding_eval/agents/_openai_client.py`) — outbound API
  call wrapper with backoff.
- `solve_single_shot` (`src/coding_eval/agents/_solver.py`) — shared host-side pipeline:
  gather context → complete → extract patch → apply-check + py-compile → bounded retry.
- `get_adapter` (`src/coding_eval/agents/__init__.py`) — registry + per-adapter env-var key
  resolution (`os.environ.get`).

### 1.3 Data stores

- Cloned target repos (read-only to adapters; patches are strings in memory).
- `data/tasks/*.jsonl` (task definitions, untrusted issue text).
- `results/leaderboard.json` / `.md` (scores; no secrets).
- No database in the eval path (semantic judge uses a local SQLite cache, untouched here).

### 1.4 Sensitive data

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — env-only; never persisted; never logged (verified).
- No PII, no credentials at rest. `.env` is gitignored; no `.env` is tracked; no live key
  material anywhere in tracked files (whole-tree `git grep` scan: clean).

---

## 2. STRIDE analysis (new OpenAI adapter data flow + touched host boundary)

| Category | Threat considered | Assessment | Evidence / mitigation |
|---|---|---|---|
| **Spoofing** | Forged provider endpoint; key from caller-passed wrong env var | LOW. SDK uses TLS to the official OpenAI endpoint. Key plumbing was generalized so each adapter resolves *its own* env var (`OPENAI_API_KEY` vs `ANTHROPIC_API_KEY`) — fixes the prior bug where `cli.py` passed the Anthropic key to every adapter. | `__init__.py:24-28,46-51`; `cli.py` now calls `get_adapter(agent_id)`. |
| **Tampering** | Malicious model output mutates host filesystem during validation; in-transit prompt tampering | LOW. `git apply --check` is a non-mutating dry run; the real `apply` happens only inside a `tempfile.mkdtemp` copy that is `rmtree`'d in `finally`. The live repo is never written. HTTPS protects the wire. | `git_apply.py:56` (`--check`); `validate.py:18-34` (temp copy + cleanup); empirical traversal tests below. |
| **Repudiation** | No audit trail of API calls / retries | LOW (acceptable for a local eval harness). Structured `structlog` events are preserved/added: `openai.retry`, `agent.apply_check_failed`, `agent.format_reprompt`, `agent.extract_fallback_raw`, `agent.py_compile_failed`. Per-task `cost_usd` flows to `TaskResult`. | `_openai_client.py:79`; `_solver.py:112,168,193,207`. |
| **Information disclosure** | API key or full prompt (which embeds issue text + repo contents) leaked to logs/errors | LOW. No log call emits the key, the `messages` list, or completion bodies. Logs carry only event names, attempt counters, error *type names*, and apply/compile errors **truncated to 500 chars**. Keys never appear in `__all__`/`repr`. | grep of all `log.*` calls in the 4 changed agent modules; `error[:500]` truncation at `_solver.py:117,168`. |
| **Denial of service** | Unbounded retries / runaway cost; huge prompt; hostile completion stalls the loop | LOW. Retry is bounded: `MAX_RETRIES = 4` (API transient) and `MAX_APPLY_ATTEMPTS = 3` (apply loop). Prompt context is budget-capped (`MAX_TOTAL_CHARS = 48_000`, `MAX_CHARS_PER_FILE = 12_000`, unchanged). Empty/`None` completion degrades to the empty-patch path, not a crash (unit-tested). **Note L-2:** the OpenAI SDK call sets no explicit per-request timeout (relies on SDK default); the backoff doubles delay without a total-time ceiling. | `_openai_client.py:30,32-37,74-88`; `_solver.py:38,100`; `completion_text` guard at `_openai_client.py:53-61`. |
| **Elevation of privilege** | (a) Prompt injection: untrusted issue/repo text steers the model. (b) Path traversal / arbitrary write via diff target paths. (c) Code execution during host-side validate/compile. | LOW–MEDIUM. (a) Prompt injection cannot reach a side-effectful tool — the single-shot adapter has NO tools; the model's only influence is the patch string, which is gated by extract → apply-check → py-compile before any sandbox use. (b) `git apply` rejects `..`, absolute, and symlink-escape targets at BOTH the check and apply stages (verified). (c) `py_compile.compile` parses/byte-compiles only — it does NOT import or execute module top-level code, so a patch with `os.system(...)` at import scope cannot run on the host. Residual: the harness adds NO path validation of its own and relies entirely on git (see M-2). | empirical tests (§3.3); `validate.py:28` (`py_compile`, not import/exec). |

---

## 3. Code & dependency review

### 3.1 Secret handling (audit item 1) — PASS

- Keys resolved from env only: `key = api_key if api_key is not None else os.environ.get(env_var)`
  (`__init__.py:50`). No hardcoded key literals anywhere in `src` (`git grep` clean).
- No key, no `messages`/prompt, no completion body is logged in any of the new/edited modules.
- `.env` is in `.gitignore` (line 1); no `.env` is tracked; no `.env` on disk; the branch diff
  introduces no secret-like assignment; whole-tree scan for `sk-...`, `AKIA...`, and PEM
  private-key headers is clean.
- `.env.example` correctly carries a placeholder `OPENAI_API_KEY=` (empty) and drops the now-
  vestigial `LANGSMITH_*` vars.

### 3.2 Dependency posture (audit item 3)

- **`openai` bump 1.53.0 → 1.57.4** — consistent across `pyproject.toml:15` and `uv.lock`
  (`specifier = "==1.57.4"`); `uv lock --check` resolves with no drift. This is a patch/minor
  bump within the stable 1.x line; the adapter uses only long-stable surface
  (`chat.completions.create`, `choices[0].message.content`, `usage.prompt_tokens/completion_tokens`,
  the `RateLimitError/InternalServerError/APIConnectionError/APITimeoutError` classes). No
  concerning transitive change observed in the lock delta. (Note: the task brief described the
  bump; the planning docs still mention "keep openai==1.53.0" — a doc/impl drift worth a one-line
  note, informational only.)
- **Removals (`langsmith`, `datasets`, `tree-sitter`)** — gone from `[project].dependencies`,
  the `datasets` mypy override removed, and all three absent from `uv.lock`. This shrinks install
  + attack surface (notably `tree-sitter`'s compiled binary). **Dangling import (M-1):**
  `scripts/precompute_contamination.py:10` still does `from datasets import ...`; with `datasets`
  removed, that one-time precompute utility now raises `ImportError`. It is off the eval hot path
  and not in the offline suite, so the suite stays green and runtime evals are unaffected — but
  the script is broken.
- **Vuln scan:** `pip-audit` / `bandit` / `safety` / `semgrep` are not installed in this
  environment and `uv tool run` could not fetch them offline, so no live CVE database was
  consulted. This is an offline static review; recommend running `pip-audit` in CI against
  `uv.lock` (see hardening checklist). `bandit -r src` is recommended for the patch-handling code.

### 3.3 Prompt injection / untrusted input (audit item 2) — empirically validated

The model OUTPUT (a patch) is the only path from an untrusted model back to the host. It is
validated on the host before the sandbox. Findings from direct experiments on git 2.50.1:

- **`git apply --check` is non-mutating** — confirmed: an actual apply of a `..` traversal patch
  left the victim file untouched (`apply-exit=128`, file unchanged). The check stage in
  `_validate_patch` therefore cannot write to disk.
- **Diff path containment is enforced by git, at both stages:**
  - `..` traversal target → `error: invalid path '../ga_victim.txt'` (exit 128), at check AND apply.
  - absolute-path target (`--- /tmp/...`) → git strips the leading `/`, treats it as repo-relative,
    fails to apply (no escape).
  - new-file-via-traversal (`/dev/null` → `b/../escape.py`) → `error: invalid path` (exit 128).
  - symlinked-directory escape → `error: affected file '...' is beyond a symbolic link`; no file
    created outside the repo.
- **Host-side py-compile does not execute model code** — `patch_py_files_compile` uses
  `py_compile.compile(..., doraise=True)`, which compiles to bytecode without importing/running
  the module. A malicious patch with top-level side effects cannot run on the host.
- **No tool exposure in the single-shot path** — `OpenAIAdapter`/`ClaudeCodeAdapter` have no
  `RepoTools` loop (that is the agentic adapter, untouched here), so prompt injection cannot
  invoke a read/grep/list side-effectful action through this adapter.
- **Gap (M-2):** `patching/extract.py` passes traversal-looking paths through verbatim
  (`a/../../etc/evil.py` is extracted unchanged) — the harness performs NO independent path
  validation and relies entirely on `git apply`'s checks. Today git's containment is robust, so
  exploitability is effectively nil; the risk is the absence of defense-in-depth if a future git
  flag (e.g. `--unsafe-paths`, `--directory`) or a git regression weakens that guarantee.

### 3.4 Injection / unsafe constructs

- No `eval`, `exec`, `os.system`, `subprocess`, `shell=True`, or `pickle` in any changed agent
  module. The `cast(Any, ...)` calls are SDK-boundary type casts only.
- SDK call arguments (`model`, `temperature`, `max_tokens`) are constants; only the prompt
  `messages` are dynamic, and they are text-only.

---

## 4. Findings table

| ID | Threat | Category | Severity | Impact | Remediation | Status |
|---|---|---|---|---|---|---|
| **M-1** | `scripts/precompute_contamination.py:10` imports `from datasets import ...` after `datasets` was removed from deps | Tampering / availability (functional break) | **Medium** | The contamination-precompute utility now fails with `ImportError`; anyone re-running it to refresh `swebench_train_embeddings.npz` is blocked. Not on the eval hot path; offline suite unaffected. | Either (a) re-add `datasets` as a `precompute`/`dev` extra that this script declares, or (b) move the `from datasets import ...` to a lazy import inside the command function and document the extra in the script header. Do NOT silently leave the broken top-level import. | Recommended (safe-fix candidate this PR) |
| **M-2** | Diff target paths reach `git apply` with no harness-level validation; `extract.py` passes `..`/absolute paths through verbatim | Elevation of privilege (path traversal) — defense-in-depth | **Medium** | Currently NOT exploitable (git rejects traversal/symlink escapes at check + apply, verified). Risk is single-layer reliance: a future `git apply` invocation flag or git regression could remove the only containment. | Add a cheap host-side guard before apply/compile: reject any extracted patch whose target paths (post-`a/`,`b/` strip) contain `..`, are absolute, or normalize outside the repo root. Keep `git apply` invoked WITHOUT `--unsafe-paths`/`--directory`. ~10 lines in `patching/extract.py` or a new check in `_validate_patch`. | **Resolved** — `patch_paths_within_repo()` in `validate.py`, wired into `_solver._validate_patch` as the first gate (before git); covered by `tests/test_patch_path_guard.py`. |
| **L-1** | OpenAI SDK call sets no explicit per-request timeout; backoff has no total-time ceiling | Denial of service (resource exhaustion) | **Low** | A hung/slow upstream could stall a task longer than intended; retries (4) compound. Bounded overall by `MAX_RETRIES`/`MAX_APPLY_ATTEMPTS`, so not unbounded. | Pass an explicit `timeout=` to `AsyncOpenAI(...)` or the `create(...)` call (e.g. 60s), mirroring a sane default; optionally cap cumulative backoff. | Recommended |
| **L-2** | `shutil.copytree(..., symlinks=True)` in `patch_py_files_compile` copies symlinks verbatim into the temp dir | Tampering (theoretical symlink write-through) | **Low** | A repo-internal symlink pointing outside the tree, combined with a patch writing through it, could in principle touch an external path during the temp-copy apply. Mitigated by git's "beyond a symbolic link" rejection (verified) and the per-run temp dir. | Acceptable as-is given git's guard; optionally `symlinks=False` (dereference) or refuse patches that target symlinked paths. | Accepted (low residual) |
| **L-3** | `git apply` containment is the sole control; behavior is git-version-dependent | Elevation of privilege (assumption) | **Low** | Verified safe on git 2.50.1; older/forked git could differ. | Document the minimum git version assumption; pair with M-2's harness-level guard. | Recommended (pairs with M-2) |
| **I-1** | Doc/impl drift: PLAN/ASSUMPTIONS say "keep `openai==1.53.0`" but the dep was bumped to 1.57.4 | Repudiation (doc accuracy) | Info | None functional; lock is consistent. | Update the planning docs to reflect 1.57.4 and the reason for the bump. | Recommended |
| **I-2** | Pricing constants (`INPUT_USD_PER_MTOK=2.5`, `OUTPUT_USD_PER_MTOK=10.0`) must move with `DEFAULT_OPENAI_MODEL` | Info (cost-accuracy) | Info | A model id change without a rate change silently mis-reports `cost_usd`. | Already documented inline (`_openai_client.py:25-28`, A4). Consider a unit test asserting model/rate co-pinning. | Accepted |
| **I-3** | Dependency vuln scan not run (no `pip-audit`/`bandit` in this env, offline) | Info (coverage gap) | Info | Known-CVE status of the bumped `openai` and transitives was not checked against a live DB. | Add `pip-audit -r` (or against `uv.lock`) and `bandit -r src` to CI. | Recommended |

---

## 5. What was remediated now

**Nothing was code-changed during this audit** — the engagement is read-only/scanning per the
brief (no source edits, no commit). All findings above are reported for the build loop to action.
The two MEDIUMs are safe, low-effort fixes; **M-1 is the recommended in-PR fix** (a dangling
import that breaks an offline utility), and **M-2** is the recommended defense-in-depth hardening.

Positively confirmed during the audit (no action needed): env-only key handling, no secret in
logs or git history, `.env` gitignored, non-mutating apply-check, non-executing py-compile,
git-enforced path containment, bounded retries, clean lockfile, green offline suite (93.15%).

---

## 6. Residual risk / accepted

- **Path containment now double-layered (M-2 resolved).** The host-side patch boundary no
  longer relies on `git apply` alone: `patch_paths_within_repo()` rejects any diff target that
  is absolute (POSIX or Windows-drive) or resolves outside the repo root, before git or
  py-compile run. `git apply`'s own check+apply rejection remains the second layer. (L-3:
  documenting a minimum git version is still recommended, but git is no longer the sole control.)
- **Symlinked temp-copy (L-2, accepted).** `copytree(symlinks=True)` is low-risk given git's
  "beyond a symbolic link" rejection and the disposable per-run temp dir.
- **No request timeout on the OpenAI call (L-1, accepted short-term).** Bounded by retry counts;
  recommend an explicit timeout for robustness.
- **Trust in the model provider.** Out of scope to mitigate — prompts (containing issue text and
  repo slices, no secrets) are sent to OpenAI/Anthropic by design; this is inherent to the
  harness's purpose and unchanged by v0.2.
- **Vuln-DB gap (I-3, accepted for this offline review).** No live CVE scan was possible here;
  delegated to CI.

---

## 7. Hardening checklist

- [ ] **M-1:** Fix the dangling `from datasets import ...` in `scripts/precompute_contamination.py`
      (lazy import + declared `precompute` extra, or re-add the dep to a dev/extra group).
- [x] **M-2:** Host-side diff-path guard added — `patch_paths_within_repo()` in `validate.py`,
      called first in `_solver._validate_patch` (rejects absolute / out-of-root targets before
      `git apply`/`py_compile`); `git apply` kept free of `--unsafe-paths`/`--directory`.
      Covered by `tests/test_patch_path_guard.py`.
- [ ] **L-1:** Set an explicit `timeout=` on the OpenAI client/call.
- [ ] **L-2:** Consider `copytree(..., symlinks=False)` or refuse symlink-targeted patches.
- [ ] **L-3 / I-3:** Document the minimum git version; add `pip-audit` (against `uv.lock`) and
      `bandit -r src` to CI.
- [ ] **I-1:** Reconcile PLAN/ASSUMPTIONS docs with the actual `openai==1.57.4` pin.
- [x] Keys env-only, never logged, `.env` gitignored, no secret committed. (verified)
- [x] Apply-check non-mutating; py-compile non-executing; diff paths git-contained. (verified)
- [x] Retries bounded; empty/None completion degrades to empty patch, no crash. (verified)
- [x] Lockfile consistent (`uv lock --check`); offline suite green (93.15%). (verified)
