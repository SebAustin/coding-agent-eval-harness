"""OpenAI single-shot agent adapter.

Uses the shared ``_solver.solve_single_shot`` pipeline and provides an OpenAI-specific
``complete`` closure that follows the §3.2 incremental-cost contract: it returns
``(assistant_text, incremental_cost_usd)`` for *this call only*; cost accumulation is
owned by the solver.

The filename is deliberately ``openai_adapter.py``, not ``openai.py``, to avoid
shadowing the ``openai`` package on import (PLAN.md §3.4 / R4).
"""

from __future__ import annotations

from typing import Any, cast

import openai

from coding_eval.agents._openai_client import (
    completion_text,
    create_completion_with_retry,
    usage_cost_usd,
)
from coding_eval.agents._solver import solve_single_shot
from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.prompts import SYSTEM_PROMPT
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.models import DEFAULT_OPENAI_MODEL

MODEL_ID = DEFAULT_OPENAI_MODEL


class OpenAIAdapter(AgentAdapter):
    """Single-shot OpenAI adapter using the shared solve loop.

    Uses the system prompt as the first message (OpenAI convention), not a kwarg
    (Anthropic convention). All retry, format-fixup, and apply-check logic is
    delegated to ``_solver.solve_single_shot``.
    """

    agent_id = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        # Construct the client LAZILY. The OpenAI SDK raises at construction when
        # api_key is None and OPENAI_API_KEY is unset, but the harness contract is
        # that an adapter is always constructible (like the Anthropic adapter) and
        # a missing key only surfaces when you actually solve. So store the key and
        # defer client creation to first use.
        self._api_key = api_key
        self._client_instance: openai.AsyncOpenAI | None = None

    @property
    def _client(self) -> openai.AsyncOpenAI:
        if self._client_instance is None:
            self._client_instance = openai.AsyncOpenAI(api_key=self._api_key)
        return self._client_instance

    @_client.setter
    def _client(self, client: openai.AsyncOpenAI) -> None:
        # Lets tests inject a mock client via ``adapter._client = AsyncMock()``.
        self._client_instance = client

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        async def complete(messages: list[dict[str, str]]) -> tuple[str, float]:
            # OpenAI takes the system prompt as the first message, not a kwarg.
            payload: list[dict[str, str]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *messages,
            ]
            response = await create_completion_with_retry(
                lambda: self._client.chat.completions.create(
                    model=MODEL_ID,
                    temperature=0,
                    max_tokens=4096,
                    messages=cast(Any, payload),
                ),
            )
            raw = completion_text(response)
            messages.append({"role": "assistant", "content": raw})
            # INCREMENTAL per the §3.2 contract: this call's cost only.
            return raw, usage_cost_usd(response.usage)

        return await solve_single_shot(
            task=task,
            repo_path=repo_path,
            complete=complete,
        )


__all__ = ["MODEL_ID", "OpenAIAdapter"]
