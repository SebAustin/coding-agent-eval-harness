# Adding agents

Step-by-step guide to registering a new coding agent in the eval harness. The
**OpenAI adapter** (`agents/openai_adapter.py`) is the reference worked example
for a new single-shot provider — follow its pattern for any API-backed agent.

## Prerequisites

- Python 3.12, `uv sync --all-extras`
- Docker (for sandbox execution)
- `ANTHROPIC_API_KEY` (required for the semantic rubric judge regardless of which
  agent you run)
- Your agent's API key (e.g. `OPENAI_API_KEY` for the `openai` adapter)

## Worked example: the OpenAI adapter

The `openai` adapter (`agent_id="openai"`) demonstrates all four steps below.
Read `src/coding_eval/agents/openai_adapter.py` alongside this guide.

### Key design decisions

1. **Reuse the shared solver** — `agents/_solver.py` owns the apply-check +
   format-fixup + bounded-retry pipeline. Your adapter only needs to supply a
   `complete(messages) -> (text, incremental_cost_usd)` closure.

2. **Incremental cost contract** — the closure returns *this call's cost only*.
   The solver sums all increments into the final `AgentSolveResult.cost_usd`.
   Do NOT return a running total (that was the old pattern in `_append_completion`).

3. **Filename** — never name your module `openai.py` (shadows the package). Use
   `openai_adapter.py` or `{name}_adapter.py`.

4. **System prompt placement** — Anthropic accepts `system=` as a kwarg;
   OpenAI takes it as the first `{"role": "system"}` message. Handle this inside
   your `complete` closure, not in the solver.

## 1. Implement `AgentAdapter`

Create `src/coding_eval/agents/{name}_adapter.py`:

```python
from __future__ import annotations

from typing import Any, cast

import your_sdk

from coding_eval.agents._openai_client import (  # or write your own primitives
    completion_text,
    create_completion_with_retry,
    usage_cost_usd,
)
from coding_eval.agents._solver import solve_single_shot
from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.prompts import SYSTEM_PROMPT
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.models import DEFAULT_OPENAI_MODEL  # or your model constant


class MyAgentAdapter(AgentAdapter):
    agent_id = "my-agent"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = your_sdk.AsyncClient(api_key=api_key)

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        async def complete(messages: list[dict[str, str]]) -> tuple[str, float]:
            # Prepend system prompt as first message (OpenAI convention).
            # For Anthropic: pass system= kwarg instead; see claude_code.py.
            payload = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
            response = await create_completion_with_retry(
                lambda: self._client.chat.completions.create(
                    model=DEFAULT_OPENAI_MODEL,
                    temperature=0,
                    max_tokens=4096,
                    messages=cast(Any, payload),
                ),
            )
            raw = completion_text(response)
            messages.append({"role": "assistant", "content": raw})
            # INCREMENTAL: this call's cost only. The solver accumulates.
            return raw, usage_cost_usd(response.usage)

        return await solve_single_shot(
            task=task,
            repo_path=repo_path,
            complete=complete,
        )


__all__ = ["MyAgentAdapter"]
```

**Contract:**

| Field | Requirement |
| --- | --- |
| `patch` | Unified diff applicable with `git apply` at `repo_path` |
| `cost_usd` | Sum of all `complete` call increments (solver owns accumulation) |
| `raw_response` | Debug text saved when patch is empty |

Reference implementations:

- `src/coding_eval/agents/openai_adapter.py` — OpenAI Chat Completions, system as first message
- `src/coding_eval/agents/claude_code.py` — Anthropic Messages API, system as kwarg (thin wrapper over solver)
- `src/coding_eval/agents/claude_code_agentic.py` — tool-using loop (does NOT use the shared solver)
- `src/coding_eval/agents/aider.py` — subprocess wrapper

If you expose tools, keep them read-only and sandboxed to the repo root (see
`RepoTools._resolve`), and bound the loop with a turn cap, a cost ceiling, and the
eval-loop wall-clock timeout (`CODING_EVAL_AGENT_TIMEOUT_S`).

**Do not** run agent code or tests inside the adapter on the host filesystem beyond
reading repo context; test execution happens in `DockerSandbox` after patch extraction.

## 2. Register in `AGENT_REGISTRY`

Add your adapter class to `AGENT_REGISTRY` and your env-var to `_API_KEY_ENV` in
`src/coding_eval/agents/__init__.py`:

```python
import os
from .my_agent_adapter import MyAgentAdapter

AGENT_REGISTRY: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "claude-code-agentic": ClaudeCodeAgenticAdapter,
    "aider": AiderAdapter,
    "openai": OpenAIAdapter,
    "my-agent": MyAgentAdapter,   # <-- add here
}

# Map adapter id -> env var holding its API key.
_API_KEY_ENV: dict[str, str] = {
    "claude-code": "ANTHROPIC_API_KEY",
    "claude-code-agentic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "my-agent": "MY_AGENT_API_KEY",  # <-- add here (or omit if no key needed)
}
```

`get_adapter(agent_id)` resolves each adapter's key from its own env var. Adapters not
in `_API_KEY_ENV` (like `aider`) are constructed argument-free.

## 3. Add `.env.example` entry

Add your key placeholder to `.env.example`:

```bash
# Required for the my-agent adapter
MY_AGENT_API_KEY=
```

## 4. Add tests

Minimum coverage (mirror `tests/test_openai_adapter.py`):

| Test | Asserts |
| --- | --- |
| Happy path | `result.patch == good_patch`; client called once |
| Apply-check retry | bad→good; `await_count == 2` |
| Exhausted retries | three bad patches; `result.patch == ""`; `await_count == 3` |
| Format-reprompt | malformed→good; `"--- format fixup ---" in result.raw_response` |
| Empty completion | `choices=[]` or empty response; `result.patch == ""`; no crash |
| **Cost single-call** | `result.cost_usd == (prompt*INPUT + completion*OUTPUT)/1e6` exactly |
| **Cost multi-call** | `result.cost_usd == pytest.approx(sum of each call's increment)` |

The two cost tests are **mandatory** — they guard the incremental-cost contract (the
solver accumulates; the closure returns the delta). Without them a cost-accumulation
bug passes all other tests silently.

```python
# pyproject.toml per-file-ignores — copy the test_claude_code.py entry:
"tests/test_my_agent.py" = ["S101", "INP001", "PT001", "PT023", "TC003", "PLR2004",
                             "S106", "SLF001", "E501", "S108", "ARG002", "PLC0415"]
```

Follow existing patterns in `tests/test_openai_adapter.py`. Mock the SDK client at the
class level if the SDK has httpx compatibility issues on import (see the docstring in
`test_openai_adapter.py` for the `patch("your_sdk.AsyncClient")` pattern).

## 5. PR requirements

Before merging an agent adapter:

1. **Lint / type / unit tests pass** — CI runs `ruff`, `mypy --strict`, `pytest`.
2. **Smoke eval** — CI runs `coding-eval run --agents claude-code --smoke`; add your
   agent to nightly once stable.
3. **Leaderboard entry on >= 5 tasks** — run locally:

   ```bash
   uv run coding-eval run --agents my-agent --limit 5 --seed 42
   ```

   Include `results/leaderboard.json` snippet or PR comment showing composite score,
   `n_total >= 5`, and contamination columns.

4. **Document API keys** — note required env vars in PR description (never commit secrets).

## 6. Nightly registration

After merge, add your agent ID to `.github/workflows/leaderboard-nightly.yml`:

```yaml
uv run coding-eval run \
  --agents claude-code \
  --agents aider \
  --agents my-agent \
  ...
```

Ensure required secrets exist in the repo settings.

## Checklist

- [ ] `AgentAdapter` subclass in `src/coding_eval/agents/{name}_adapter.py`
- [ ] Entry in `AGENT_REGISTRY` and `_API_KEY_ENV` (`agents/__init__.py`)
- [ ] `.env.example` documents the required API key placeholder
- [ ] Unit tests with mocked client (including 2 mandatory cost tests)
- [ ] `pyproject.toml` per-file-ignores entry for the test file
- [ ] Local smoke: `--limit 5` produces valid patches on >= 1 task
- [ ] PR shows leaderboard metrics for >= 5 tasks
- [ ] No API keys in source or commits

## Related docs

- [Methodology](methodology.md) — execution and reproducibility
- [Rubric design](rubric_design.md) — how patches are scored
- [Contamination analysis](contamination_analysis.md) — automatic per-task flagging
