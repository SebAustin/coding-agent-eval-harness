from __future__ import annotations

import asyncio
from typing import Any, cast

import anthropic
import structlog
from anthropic.types import MessageParam

from coding_eval.agents._common import message_text, usage_cost_usd
from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.context import format_apply_failure_context, gather_repo_context
from coding_eval.agents.prompts import AGENTIC_NO_OUTPUT_REPROMPT, AGENTIC_SYSTEM_PROMPT
from coding_eval.agents.repo_tools import TOOL_SPECS, RepoTools
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.models import DEFAULT_AGENT_MODEL
from coding_eval.patching.extract import extract_unified_patch
from coding_eval.patching.git_apply import check_unified_diff
from coding_eval.patching.validate import patch_py_files_compile

log = structlog.get_logger(__name__)

MODEL_ID = DEFAULT_AGENT_MODEL
MAX_TURNS = 24
# Final turns where tools are withheld so the model must commit to a diff instead
# of exploring forever; the reserve also leaves retries if the first apply fails.
FORCED_DIFF_TURNS = 3
MAX_TOKENS = 8192
FORCE_DIFF_NUDGE = (
    "Tool budget nearly exhausted. After these results, stop exploring and reply "
    "with ONLY the final unified diff starting with '---'."
)
FORCE_DIFF_REPROMPT = (
    "You can no longer use tools. Based on everything you have already read, commit "
    "to your best fix now even if you are not fully certain — a concrete diff is far "
    "better than none. Reply with ONLY a unified diff starting with '--- a/<path>', "
    "using line numbers and context lines from the files you read. No prose, no "
    "questions, no markdown fence."
)


class ClaudeCodeAgenticAdapter(AgentAdapter):
    """Tool-using variant that explores the repo before emitting a diff.

    The single-shot adapter sends a fixed slice of context and asks for a diff in
    one turn; tasks whose fix spans files the heuristics never surfaced fail
    because the model can only guess at code it cannot see. This adapter gives the
    model read-only ``read_file`` / ``grep`` / ``list_dir`` tools over the clone
    and loops until it produces an applicable diff. Execution stays in the Docker
    sandbox unchanged — only host-side patch generation gains tools.
    """

    agent_id = "claude-code-agentic"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        tools = RepoTools(repo_path)
        repo_context = await asyncio.to_thread(
            gather_repo_context,
            repo_path,
            task.test_files,
            issue_body=task.issue_body,
            issue_title=task.issue_title,
        )
        messages: list[MessageParam] = [
            {"role": "user", "content": _build_initial_prompt(task, repo_context)},
        ]
        cost = 0.0
        raw_log: list[str] = []
        patch = ""

        for turn in range(MAX_TURNS):
            tools_enabled = turn < MAX_TURNS - FORCED_DIFF_TURNS
            message, cost = await self._call(messages, cost, use_tools=tools_enabled)
            text = message_text(message)
            if text.strip():
                raw_log.append(text)
            messages.append(
                cast("MessageParam", {"role": "assistant", "content": _assistant_content(message)}),
            )

            tool_calls = [block for block in message.content if block.type == "tool_use"]
            if tool_calls:
                results = await self._run_tools(tools, tool_calls, task.task_id)
                # Warn the model once it is about to lose tool access so it spends
                # its remaining turns producing the diff, not mid-exploration.
                if turn + 1 >= MAX_TURNS - FORCED_DIFF_TURNS:
                    results.append({"type": "text", "text": FORCE_DIFF_NUDGE})
                messages.append(cast("MessageParam", {"role": "user", "content": results}))
                continue

            patch = extract_unified_patch(text)
            if not patch.strip():
                if turn >= MAX_TURNS - 1:
                    break
                log.info("agentic.no_output_reprompt", task_id=task.task_id, turn=turn + 1)
                reprompt = AGENTIC_NO_OUTPUT_REPROMPT if tools_enabled else FORCE_DIFF_REPROMPT
                messages.append({"role": "user", "content": reprompt})
                continue

            ok, apply_error = await self._validate_patch(repo_path, patch)
            if ok:
                return AgentSolveResult(
                    patch=patch,
                    cost_usd=cost,
                    raw_response=_join_raw_log(raw_log),
                )
            if turn >= MAX_TURNS - 1:
                break
            log.info(
                "agentic.apply_check_failed",
                task_id=task.task_id,
                turn=turn + 1,
                error=apply_error[:500],
            )
            messages.append(
                {
                    "role": "user",
                    "content": _build_apply_retry_prompt(repo_path, task, apply_error, patch),
                },
            )

        return AgentSolveResult(patch="", cost_usd=cost, raw_response=_join_raw_log(raw_log))

    async def _call(
        self,
        messages: list[MessageParam],
        cost: float,
        *,
        use_tools: bool,
    ) -> tuple[anthropic.types.Message, float]:
        if use_tools:
            message = await self._client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                temperature=0,
                system=AGENTIC_SYSTEM_PROMPT,
                tools=cast("Any", TOOL_SPECS),
                messages=messages,
            )
        else:
            message = await self._client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                temperature=0,
                system=AGENTIC_SYSTEM_PROMPT,
                messages=messages,
            )
        return message, cost + usage_cost_usd(message.usage)

    async def _run_tools(
        self,
        tools: RepoTools,
        tool_calls: list[Any],
        task_id: str,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for block in tool_calls:
            output = await asyncio.to_thread(tools.dispatch, block.name, block.input)
            log.info(
                "agentic.tool_call",
                task_id=task_id,
                tool=block.name,
                args=block.input,
                result_chars=len(output),
            )
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output},
            )
        return results

    async def _validate_patch(self, repo_path: str, patch: str) -> tuple[bool, str]:
        ok, error = await asyncio.to_thread(check_unified_diff, repo_path, patch)
        if not ok:
            return False, error
        compile_ok, compile_error = await asyncio.to_thread(
            patch_py_files_compile,
            repo_path,
            patch,
        )
        if not compile_ok:
            log.info("agentic.py_compile_failed", error=compile_error[:500])
            return False, compile_error
        return True, ""


def _build_initial_prompt(task: Task, repo_context: str) -> str:
    parts = [
        f"Issue: {task.issue_title}\n\n{task.issue_body}\n\nRepository: {task.repo}",
        "Use the read_file, grep, and list_dir tools to find every file the fix must "
        "touch, then reply with the unified diff. Explore efficiently: your tool "
        "budget is limited, so prefer grep to locate code and read_file with "
        "start_line/end_line for large files, and stop exploring once you can write "
        "the fix.",
    ]
    if repo_context:
        parts.append(repo_context)
    return "\n\n".join(parts)


def _build_apply_retry_prompt(
    repo_path: str,
    task: Task,
    apply_error: str,
    previous_patch: str,
) -> str:
    failure_slices = format_apply_failure_context(repo_path, apply_error)
    parts = [
        "Your previous patch did not apply cleanly.",
        f"Apply error:\n{apply_error}",
        f"Previous patch:\n{previous_patch}",
    ]
    if failure_slices:
        parts.append(
            "Numbered source around the failure (copy these context lines exactly):\n"
            f"{failure_slices}",
        )
    else:
        parts.append(
            "Use read_file to re-read the target files and copy context lines exactly.",
        )
    parts.append(
        f"Issue reminder: {task.issue_title}\n\n"
        "Reply with a corrected unified diff only, starting with '---'.",
    )
    return "\n\n".join(parts)


def _assistant_content(message: anthropic.types.Message) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in message.content:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                },
            )
    return blocks


def _join_raw_log(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part.strip())


__all__ = ["MAX_TURNS", "MODEL_ID", "ClaudeCodeAgenticAdapter"]
