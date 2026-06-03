from __future__ import annotations

import re

import anthropic

from coding_eval.agents.base import AgentAdapter
from coding_eval.dataset.schema import Task

MODEL_ID = "claude-sonnet-4-5-20251022"
INPUT_USD_PER_MTOK = 3.0
OUTPUT_USD_PER_MTOK = 15.0

SYSTEM_PROMPT = (
    "You are a software engineer. Produce a minimal unified diff patch "
    "that fixes the described issue. Output ONLY the diff, starting with '---'. "
    "No explanation, no markdown fence."
)

_DIFF_START_RE = re.compile(r"^---\s", re.MULTILINE)


class ClaudeCodeAdapter(AgentAdapter):
    agent_id = "claude-code"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> tuple[str, float]:
        _ = repo_path
        user_content = (
            f"Issue: {task.issue_title}\n\n{task.issue_body}\n\nRepository: {task.repo}"
        )
        message = await self._client.messages.create(
            model=MODEL_ID,
            max_tokens=4096,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        patch = _extract_patch(_message_text(message))
        cost = _usage_cost_usd(message.usage)
        return patch, cost


def _message_text(message: anthropic.types.Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


def _extract_patch(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    match = _DIFF_START_RE.search(stripped)
    if match is None:
        return ""
    return stripped[match.start() :].strip()


def _usage_cost_usd(usage: anthropic.types.Usage) -> float:
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    return (input_tokens * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / 1_000_000


__all__ = ["ClaudeCodeAdapter", "MODEL_ID"]
