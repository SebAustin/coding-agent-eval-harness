from __future__ import annotations

import asyncio

import anthropic
import structlog
from anthropic.types import MessageParam

from coding_eval.agents._common import (
    create_message_with_retry,
    message_text,
    usage_cost_usd,
)
from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.context import (
    format_apply_failure_context,
    format_patch_target_files,
    gather_repo_context,
)
from coding_eval.agents.prompts import FORMAT_REPROMPT, FORMAT_REPROMPT_STRICT, SYSTEM_PROMPT
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.models import DEFAULT_AGENT_MODEL
from coding_eval.patching.extract import extract_unified_patch, looks_like_diff_attempt
from coding_eval.patching.git_apply import check_unified_diff
from coding_eval.patching.validate import patch_py_files_compile

log = structlog.get_logger(__name__)

MODEL_ID = DEFAULT_AGENT_MODEL
MAX_APPLY_ATTEMPTS = 3


class ClaudeCodeAdapter(AgentAdapter):
    agent_id = "claude-code"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        repo_context = await asyncio.to_thread(
            gather_repo_context,
            repo_path,
            task.test_files,
            issue_body=task.issue_body,
            issue_title=task.issue_title,
        )
        user_content = _build_user_prompt(task, repo_context)
        messages: list[MessageParam] = [{"role": "user", "content": user_content}]
        cost = 0.0
        raw_log: list[str] = []

        raw, cost = await self._append_completion(messages, cost)
        raw_log.append(raw)
        patch, cost, fixup_raw = await self._extract_with_format_fixup(
            messages,
            raw,
            cost,
            fallback_raws=[raw],
        )
        if fixup_raw:
            raw_log.append(f"--- format fixup ---\n{fixup_raw}")

        for attempt in range(MAX_APPLY_ATTEMPTS):
            if not patch.strip():
                break

            ok, apply_error = await self._validate_patch(repo_path, patch)
            if ok:
                return AgentSolveResult(
                    patch=patch,
                    cost_usd=cost,
                    raw_response=_join_raw_log(raw_log),
                )

            log.info(
                "agent.apply_check_failed" if attempt == 0 else "agent.retry_apply_check_failed",
                task_id=task.task_id,
                attempt=attempt + 1,
                error=apply_error[:500],
            )

            if attempt >= MAX_APPLY_ATTEMPTS - 1:
                break

            messages.append(
                {
                    "role": "user",
                    "content": _build_retry_prompt(
                        task=task,
                        repo_path=repo_path,
                        apply_error=apply_error,
                        previous_patch=patch,
                        attempt=attempt + 2,
                    ),
                },
            )
            retry_raw, cost = await self._append_completion(messages, cost)
            raw_log.append(f"--- retry {attempt + 2} ---\n{retry_raw}")
            patch, cost, retry_fixup_raw = await self._extract_with_format_fixup(
                messages,
                retry_raw,
                cost,
                fallback_raws=[retry_raw, raw],
            )
            if retry_fixup_raw:
                raw_log.append(f"--- format fixup (retry {attempt + 2}) ---\n{retry_fixup_raw}")

        return AgentSolveResult(
            patch="",
            cost_usd=cost,
            raw_response=_join_raw_log(raw_log),
        )

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
            log.info("agent.py_compile_failed", error=compile_error[:500])
            return False, compile_error
        return True, ""

    async def _append_completion(
        self,
        messages: list[MessageParam],
        cost: float,
    ) -> tuple[str, float]:
        message = await create_message_with_retry(
            lambda: self._client.messages.create(
                model=MODEL_ID,
                max_tokens=4096,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=messages,
            ),
        )
        raw = message_text(message)
        messages.append({"role": "assistant", "content": raw})
        return raw, cost + usage_cost_usd(message.usage)

    async def _extract_with_format_fixup(
        self,
        messages: list[MessageParam],
        raw: str,
        cost: float,
        *,
        fallback_raws: list[str] | None = None,
    ) -> tuple[str, float, str]:
        patch = extract_unified_patch(raw)
        if patch.strip() or not looks_like_diff_attempt(raw):
            return patch, cost, ""

        fixup_log: list[str] = []
        for attempt, reprompt in enumerate((FORMAT_REPROMPT, FORMAT_REPROMPT_STRICT), start=1):
            log.info(
                "agent.format_reprompt", reason="extract_empty_with_diff_marker", attempt=attempt
            )
            messages.append({"role": "user", "content": reprompt})
            fix_raw, cost = await self._append_completion(messages, cost)
            fixup_log.append(fix_raw)
            patch = extract_unified_patch(fix_raw)
            if patch.strip():
                return patch, cost, "\n\n".join(fixup_log)
            if not looks_like_diff_attempt(fix_raw):
                break

        for fallback in fallback_raws or []:
            patch = extract_unified_patch(fallback)
            if patch.strip():
                log.info("agent.extract_fallback_raw")
                return patch, cost, "\n\n".join(fixup_log)

        return "", cost, "\n\n".join(fixup_log)


def _build_user_prompt(task: Task, repo_context: str) -> str:
    parts = [
        f"Issue: {task.issue_title}\n\n{task.issue_body}\n\nRepository: {task.repo}",
    ]
    if repo_context:
        parts.append(repo_context)
    return "\n\n".join(parts)


def _build_retry_prompt(
    *,
    task: Task,
    repo_path: str,
    apply_error: str,
    previous_patch: str,
    attempt: int,
) -> str:
    failure_slices = format_apply_failure_context(repo_path, apply_error)
    file_slices = format_patch_target_files(
        repo_path,
        previous_patch,
        apply_error=apply_error,
    )
    parts = [
        f"Your previous patch failed validation (attempt {attempt - 1}/{MAX_APPLY_ATTEMPTS}).",
        "The hunk line numbers and context lines MUST match the numbered source below exactly.",
        f"Apply error:\n{apply_error}",
        f"Previous patch:\n{previous_patch}",
    ]
    if failure_slices:
        parts.append(
            "Numbered source around the apply failure (use these exact lines as context):\n"
            f"{failure_slices}",
        )
    elif file_slices:
        parts.append(
            "Current file contents at base commit (line numbers shown as N| code):\n"
            f"{file_slices}",
        )
    parts.append(
        f"Issue reminder: {task.issue_title}\n\n"
        "Produce a corrected unified diff only, starting with '---'. "
        "Each @@ header must reference line numbers that match the numbered source."
    )
    return "\n\n".join(parts)


def _join_raw_log(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part.strip())


__all__ = ["MAX_APPLY_ATTEMPTS", "MODEL_ID", "ClaudeCodeAdapter"]
