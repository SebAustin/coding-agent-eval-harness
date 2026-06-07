# Adding agents

Step-by-step guide to registering a new coding agent in the eval harness.

## Prerequisites

- Python 3.12, `uv sync --all-extras`
- Docker (for sandbox execution)
- `ANTHROPIC_API_KEY` (required for Claude-based agents and the semantic judge)

## 1. Implement `AgentAdapter`

Create `src/coding_eval/agents/{name}.py`:

```python
from __future__ import annotations

from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task


class MyAgentAdapter(AgentAdapter):
    agent_id = "my-agent"

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        # Call your agent API on the host; return a unified diff patch string.
        patch = "..."  # unified diff
        cost_usd = 0.0
        return AgentSolveResult(patch=patch, cost_usd=cost_usd, raw_response="")
```

**Contract:**

| Field | Requirement |
| --- | --- |
| `patch` | Unified diff applicable with `git apply` at `repo_path` |
| `cost_usd` | Total API spend for this task (0.0 if unknown) |
| `raw_response` | Optional debug text saved when patch is empty |

Reference implementations:

- `src/coding_eval/agents/claude_code.py` — Anthropic Messages API, apply-check retry (single-shot)
- `src/coding_eval/agents/claude_code_agentic.py` — tool-using loop: read-only
  `read_file`/`grep`/`list_dir` over the clone (`repo_tools.py`), forced-diff turns,
  cost ceiling. Use this pattern when a fix needs multi-file exploration.
- `src/coding_eval/agents/aider.py` — subprocess wrapper

If you expose tools, keep them read-only and sandboxed to the repo root (see
`RepoTools._resolve`), and bound the loop with a turn cap, a cost ceiling, and the
eval-loop wall-clock timeout (`CODING_EVAL_AGENT_TIMEOUT_S`).

**Do not** run agent code or tests inside the adapter on the host filesystem beyond
reading repo context; test execution happens in `DockerSandbox` after patch extraction.

## 2. Register in `AGENT_REGISTRY`

Add your adapter class to `AGENT_REGISTRY` in `src/coding_eval/agents/__init__.py`:

```python
from .my_agent import MyAgentAdapter

AGENT_REGISTRY: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "claude-code-agentic": ClaudeCodeAgenticAdapter,
    "aider": AiderAdapter,
    "my-agent": MyAgentAdapter,
}
```

`cli.py` resolves agents via `get_adapter()` imported from this module. The registry key
is the CLI `--agents` value.

If your adapter takes an `api_key` constructor kwarg, add its id to `_API_KEY_AGENTS`
in `agents/__init__.py`; `get_adapter()` passes the key to those and constructs all
others argument-free.

## 3. Add tests

Minimum coverage:

| Test | Purpose |
| --- | --- |
| Unit test with mocked API | Patch extraction, cost accounting, error paths |
| Smoke invocation | `coding-eval run --agents my-agent --limit 1 --smoke` locally |

Follow existing patterns in `tests/test_run.py` and `tests/test_agent_context.py`.
Sandbox integration tests use `@pytest.mark.sandbox` and are excluded from default CI.

## 4. PR requirements

Before merging an agent adapter:

1. **Lint / type / unit tests pass** — CI runs `ruff`, `mypy --strict`, `pytest`.
2. **Smoke eval** — CI runs `coding-eval run --agents claude-code --smoke`; add your
   agent to nightly once stable.
3. **Leaderboard entry on ≥ 5 tasks** — run locally:

   ```bash
   uv run coding-eval run --agents my-agent --limit 5 --seed 42
   ```

   Include `results/leaderboard.json` snippet or PR comment showing composite score,
   `n_total ≥ 5`, and contamination columns.

4. **Document API keys** — note required env vars in PR description (never commit secrets).

## 5. Nightly registration

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

- [ ] `AgentAdapter` subclass in `src/coding_eval/agents/{name}.py`
- [ ] Entry in `AGENT_REGISTRY` (`agents/__init__.py`)
- [ ] `get_adapter()` handles constructor if needed
- [ ] Unit tests with mocked external calls
- [ ] Local smoke: `--limit 5` produces valid patches on ≥ 1 task
- [ ] PR shows leaderboard metrics for ≥ 5 tasks
- [ ] No API keys in source or commits

## Related docs

- [Methodology](methodology.md) — execution and reproducibility
- [Rubric design](rubric_design.md) — how patches are scored
- [Contamination analysis](contamination_analysis.md) — automatic per-task flagging
