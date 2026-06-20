"""Pinned model IDs for reproducible evals."""

# Sonnet 4.5 snapshot (see platform.claude.com/docs/en/about-claude/models/overview)
CLAUDE_SONNET_4_5 = "claude-sonnet-4-5-20250929"

# Default for agent adapter + semantic judge (temperature=0 in callers)
DEFAULT_AGENT_MODEL = CLAUDE_SONNET_4_5
DEFAULT_JUDGE_MODEL = CLAUDE_SONNET_4_5

# OpenAI default for the openai adapter (temperature=0 in caller). Pinned snapshot
# for reproducibility; swappable via env/override. Pricing lives in
# agents/_openai_client.py and MUST move with this id (A4).
GPT_4O = "gpt-4o-2024-11-20"
DEFAULT_OPENAI_MODEL = GPT_4O

__all__ = [
    "CLAUDE_SONNET_4_5",
    "DEFAULT_AGENT_MODEL",
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "GPT_4O",
]
