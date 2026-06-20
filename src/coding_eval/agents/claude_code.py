from __future__ import annotations

from typing import Any, cast

import anthropic

from coding_eval.agents._common import (
    create_message_with_retry,
    message_text,
    usage_cost_usd,
)
from coding_eval.agents._solver import solve_single_shot
from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.prompts import SYSTEM_PROMPT
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.models import DEFAULT_AGENT_MODEL

MODEL_ID = DEFAULT_AGENT_MODEL
MAX_APPLY_ATTEMPTS = 3


class ClaudeCodeAdapter(AgentAdapter):
    agent_id = "claude-code"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        async def complete(messages: list[dict[str, str]]) -> tuple[str, float]:
            message = await create_message_with_retry(
                lambda: self._client.messages.create(
                    model=MODEL_ID,
                    max_tokens=4096,
                    temperature=0,
                    system=SYSTEM_PROMPT,
                    messages=cast(Any, messages),
                ),
            )
            raw = message_text(message)
            messages.append({"role": "assistant", "content": raw})
            # INCREMENTAL: this call's cost only. The solver accumulates the total.
            # (Was `cost + usage_cost_usd(...)` cumulative; now just the delta.)
            return raw, usage_cost_usd(message.usage)

        return await solve_single_shot(
            task=task,
            repo_path=repo_path,
            complete=complete,
        )


__all__ = ["MAX_APPLY_ATTEMPTS", "MODEL_ID", "ClaudeCodeAdapter"]
