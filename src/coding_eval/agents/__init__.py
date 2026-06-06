from __future__ import annotations

from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.result import AgentSolveResult

from .aider import AiderAdapter
from .claude_code import ClaudeCodeAdapter

AGENT_REGISTRY: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "aider": AiderAdapter,
}

_ADAPTERS = AGENT_REGISTRY


def get_adapter(agent_id: str, *, api_key: str | None = None) -> AgentAdapter:
    adapter_cls = _ADAPTERS.get(agent_id)
    if adapter_cls is None:
        supported = ", ".join(sorted(_ADAPTERS))
        msg = f"Unknown agent {agent_id!r}; supported: {supported}"
        raise ValueError(msg)
    if agent_id == "claude-code":
        return ClaudeCodeAdapter(api_key=api_key)
    return adapter_cls()


__all__ = [
    "AGENT_REGISTRY",
    "AgentAdapter",
    "AgentSolveResult",
    "AiderAdapter",
    "ClaudeCodeAdapter",
    "get_adapter",
]
