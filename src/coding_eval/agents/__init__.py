from __future__ import annotations

from typing import cast

from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.result import AgentSolveResult

from .aider import AiderAdapter
from .claude_code import ClaudeCodeAdapter
from .claude_code_agentic import ClaudeCodeAgenticAdapter

AGENT_REGISTRY: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "claude-code-agentic": ClaudeCodeAgenticAdapter,
    "aider": AiderAdapter,
}

_ADAPTERS = AGENT_REGISTRY

# Adapters that take an Anthropic API key; all others are constructed argument-free.
_API_KEY_AGENTS = frozenset({"claude-code", "claude-code-agentic"})


def get_adapter(agent_id: str, *, api_key: str | None = None) -> AgentAdapter:
    adapter_cls = _ADAPTERS.get(agent_id)
    if adapter_cls is None:
        supported = ", ".join(sorted(_ADAPTERS))
        msg = f"Unknown agent {agent_id!r}; supported: {supported}"
        raise ValueError(msg)
    if agent_id in _API_KEY_AGENTS:
        return cast("type[ClaudeCodeAdapter]", adapter_cls)(api_key=api_key)
    return adapter_cls()


__all__ = [
    "AGENT_REGISTRY",
    "AgentAdapter",
    "AgentSolveResult",
    "AiderAdapter",
    "ClaudeCodeAdapter",
    "ClaudeCodeAgenticAdapter",
    "get_adapter",
]
