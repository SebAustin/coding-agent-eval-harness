"""Pinned Anthropic model IDs for reproducible evals."""

# Sonnet 4.5 snapshot (see platform.claude.com/docs/en/about-claude/models/overview)
CLAUDE_SONNET_4_5 = "claude-sonnet-4-5-20250929"

# Default for agent adapter + semantic judge (temperature=0 in callers)
DEFAULT_AGENT_MODEL = CLAUDE_SONNET_4_5
DEFAULT_JUDGE_MODEL = CLAUDE_SONNET_4_5

__all__ = [
    "CLAUDE_SONNET_4_5",
    "DEFAULT_AGENT_MODEL",
    "DEFAULT_JUDGE_MODEL",
]
