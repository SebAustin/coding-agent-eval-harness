from __future__ import annotations

import os
from typing import cast

from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.result import AgentSolveResult

from .aider import AiderAdapter
from .claude_code import ClaudeCodeAdapter
from .claude_code_agentic import ClaudeCodeAgenticAdapter
from .openai_adapter import OpenAIAdapter

AGENT_REGISTRY: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "claude-code-agentic": ClaudeCodeAgenticAdapter,
    "aider": AiderAdapter,
    "openai": OpenAIAdapter,
}

_ADAPTERS = AGENT_REGISTRY

# Adapters that take an api_key kwarg, and the env var each resolves it from.
_API_KEY_ENV: dict[str, str] = {
    "claude-code": "ANTHROPIC_API_KEY",
    "claude-code-agentic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def get_adapter(agent_id: str, *, api_key: str | None = None) -> AgentAdapter:
    """Return a constructed adapter for ``agent_id``.

    If the adapter requires an API key, the key is resolved in priority order:
    1. The explicit ``api_key`` argument (useful for test injection).
    2. The adapter's designated env var (e.g. ``ANTHROPIC_API_KEY`` for Claude,
       ``OPENAI_API_KEY`` for OpenAI).

    Adapters without a key requirement (``aider``) are constructed argument-free.
    """
    adapter_cls = _ADAPTERS.get(agent_id)
    if adapter_cls is None:
        supported = ", ".join(sorted(_ADAPTERS))
        msg = f"Unknown agent {agent_id!r}; supported: {supported}"
        raise ValueError(msg)
    env_var = _API_KEY_ENV.get(agent_id)
    if env_var is None:
        return adapter_cls()
    # Explicit api_key wins (test injection); else resolve from the adapter's env var.
    key = api_key if api_key is not None else os.environ.get(env_var)
    return cast("type[ClaudeCodeAdapter]", adapter_cls)(api_key=key)


__all__ = [
    "AGENT_REGISTRY",
    "AgentAdapter",
    "AgentSolveResult",
    "AiderAdapter",
    "ClaudeCodeAdapter",
    "ClaudeCodeAgenticAdapter",
    "OpenAIAdapter",
    "get_adapter",
]
