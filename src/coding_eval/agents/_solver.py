"""Shared single-shot solve loop, provider-parameterized via a CompletionFn callback.

The solver owns the apply-check + format-fixup + bounded-retry pipeline that is
identical across single-shot providers (Claude single-shot, OpenAI). Each provider
supplies a ``complete`` callback conforming to the CompletionFn contract (below) and
the solver handles all orchestration and **cost accumulation**.

Cost-accumulation contract (§3.2):
  - The ``complete`` callback returns the INCREMENTAL cost of exactly one call.
  - The solver sums these increments into a running ``cost`` total.
  - The final total is placed on ``AgentSolveResult.cost_usd``.
  - This is a deliberate semantic change from ClaudeCodeAdapter._append_completion,
    which returned the cumulative total. The invariant is that the sum of all
    increments equals the old cumulative total at every return point.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog

from coding_eval.agents.context import (
    format_apply_failure_context,
    format_patch_target_files,
    gather_repo_context,
)
from coding_eval.agents.prompts import FORMAT_REPROMPT, FORMAT_REPROMPT_STRICT
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.patching.extract import extract_unified_patch, looks_like_diff_attempt
from coding_eval.patching.git_apply import check_unified_diff
from coding_eval.patching.validate import patch_py_files_compile

log = structlog.get_logger(__name__)

MAX_APPLY_ATTEMPTS = 3


class CompletionFn(Protocol):
    """Provider-specific: send the running message list, return one assistant turn.

    CONTRACT (one, unambiguous): the closure returns the **incremental** cost of
    *this single call only* — ``(assistant_text, incremental_cost_usd)`` — and
    MUST append the assistant's reply to ``messages`` (so the next turn sees it).
    The solver, NOT the closure, owns running-total accumulation: it sums each
    returned increment into its local ``cost`` and puts the final total on
    ``AgentSolveResult.cost_usd``.
    """

    async def __call__(self, messages: list[dict[str, str]]) -> tuple[str, float]: ...


async def solve_single_shot(
    *,
    task: Task,
    repo_path: str,
    complete: CompletionFn,
    max_apply_attempts: int = MAX_APPLY_ATTEMPTS,
) -> AgentSolveResult:
    """Execute the single-shot solve pipeline for a provider-parameterized completion.

    Gathers repo context, builds the user prompt, calls ``complete``, extracts a
    unified patch (with format-fixup reprompts if needed), then validates via
    apply-check + py-compile. Retries up to ``max_apply_attempts`` times on
    apply failure, each time providing the error and prior patch as context.

    Cost accumulation: each ``complete`` call returns an incremental cost; this
    function sums them into a running total and places it on the result.
    """
    repo_context = await asyncio.to_thread(
        gather_repo_context,
        repo_path,
        task.test_files,
        issue_body=task.issue_body,
        issue_title=task.issue_title,
    )
    user_content = _build_user_prompt(task, repo_context)
    messages: list[dict[str, str]] = [{"role": "user", "content": user_content}]
    cost = 0.0
    raw_log: list[str] = []

    # Accumulation point 1: initial completion.
    raw, inc = await complete(messages)
    cost += inc
    raw_log.append(raw)

    # Accumulation points 2 (format-fixup loop, 0-2 calls inside helper).
    patch, cost, fixup_raw = await _extract_with_format_fixup(
        messages,
        raw,
        cost,
        complete,
        fallback_raws=[raw],
    )
    if fixup_raw:
        raw_log.append(f"--- format fixup ---\n{fixup_raw}")

    for attempt in range(max_apply_attempts):
        if not patch.strip():
            break

        ok, apply_error = await _validate_patch(repo_path, patch)
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

        if attempt >= max_apply_attempts - 1:
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
                    max_apply_attempts=max_apply_attempts,
                ),
            },
        )
        # Accumulation point 3: each apply-retry completion (0-2 calls total).
        retry_raw, inc = await complete(messages)
        cost += inc
        raw_log.append(f"--- retry {attempt + 2} ---\n{retry_raw}")

        # Accumulation point 4: format-fixup after each retry (0-2 calls per retry).
        patch, cost, retry_fixup_raw = await _extract_with_format_fixup(
            messages,
            retry_raw,
            cost,
            complete,
            fallback_raws=[retry_raw, raw],
        )
        if retry_fixup_raw:
            raw_log.append(f"--- format fixup (retry {attempt + 2}) ---\n{retry_fixup_raw}")

    return AgentSolveResult(
        patch="",
        cost_usd=cost,
        raw_response=_join_raw_log(raw_log),
    )


async def _validate_patch(repo_path: str, patch: str) -> tuple[bool, str]:
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


async def _extract_with_format_fixup(
    messages: list[dict[str, str]],
    raw: str,
    cost: float,
    complete: CompletionFn,
    *,
    fallback_raws: list[str] | None = None,
) -> tuple[str, float, str]:
    """Extract a unified patch; re-prompt for format if extraction fails but diff looks present.

    Returns ``(patch, updated_cost, fixup_log_text)``.
    The ``cost`` parameter is the running total coming in; increments from any
    reprompt calls are added and the new total is returned.
    """
    patch = extract_unified_patch(raw)
    if patch.strip() or not looks_like_diff_attempt(raw):
        return patch, cost, ""

    fixup_log: list[str] = []
    for attempt, reprompt in enumerate((FORMAT_REPROMPT, FORMAT_REPROMPT_STRICT), start=1):
        log.info("agent.format_reprompt", reason="extract_empty_with_diff_marker", attempt=attempt)
        messages.append({"role": "user", "content": reprompt})
        fix_raw, inc = await complete(messages)
        cost += inc
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
    max_apply_attempts: int = MAX_APPLY_ATTEMPTS,
) -> str:
    failure_slices = format_apply_failure_context(repo_path, apply_error)
    file_slices = format_patch_target_files(
        repo_path,
        previous_patch,
        apply_error=apply_error,
    )
    parts = [
        f"Your previous patch failed validation (attempt {attempt - 1}/{max_apply_attempts}).",
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


__all__ = ["MAX_APPLY_ATTEMPTS", "CompletionFn", "solve_single_shot"]
