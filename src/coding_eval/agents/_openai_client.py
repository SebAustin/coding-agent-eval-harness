"""OpenAI provider primitives: retry, incremental-cost accounting, text extraction.

Mirror of ``_common.py`` for the OpenAI SDK; kept separate so ``_common.py``'s
Anthropic types and imports are untouched and the existing import graph is stable.

Pricing note: gpt-4o rates at 2.50 / 10.00 USD per million tokens.
If ``DEFAULT_OPENAI_MODEL`` changes, update BOTH constants here and the model id
in ``models.py`` (rates must move with the model — see PLAN.md §3.7, A4).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import openai
import structlog
from openai.types.chat import ChatCompletion

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = structlog.get_logger(__name__)

# gpt-4o pricing (USD per million tokens). If DEFAULT_OPENAI_MODEL changes,
# update BOTH constants here and the model id in models.py (see A4).
INPUT_USD_PER_MTOK = 2.5
OUTPUT_USD_PER_MTOK = 10.0

MAX_RETRIES = 4
RETRY_BASE_DELAY_S = 1.0
_RETRYABLE_ERRORS = (
    openai.RateLimitError,  # 429
    openai.InternalServerError,  # >=500
    openai.APIConnectionError,  # network drop
    openai.APITimeoutError,  # request timeout
)


def usage_cost_usd(usage: object) -> float:
    """Return the INCREMENTAL cost for one completion (per the §3.2 contract).

    Typed ``object`` + ``getattr`` defensively because mocked ``usage`` in tests
    is a ``MagicMock``; the real type is ``CompletionUsage``.
    """
    if usage is None:
        return 0.0
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    return (prompt * INPUT_USD_PER_MTOK + completion * OUTPUT_USD_PER_MTOK) / 1_000_000


def completion_text(response: ChatCompletion) -> str:
    """Extract text from a ChatCompletion, guarding empty choices (refusals / 5xx).

    Returns ``""`` when ``choices`` is empty so the solver degrades gracefully
    to the empty-patch path rather than raising an ``IndexError``.
    """
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


async def create_completion_with_retry(
    make_call: Callable[[], Awaitable[ChatCompletion]],
) -> ChatCompletion:
    """Await ``make_call`` with exponential backoff on transient OpenAI API errors.

    Mirror of ``_common.create_message_with_retry`` for the OpenAI SDK.
    Retries on rate-limit / 5xx / connection / timeout errors up to
    ``MAX_RETRIES`` times, doubling the delay each time. Non-transient errors
    and the final attempt propagate immediately.
    """
    delay = RETRY_BASE_DELAY_S
    for attempt in range(MAX_RETRIES):
        try:
            return await make_call()
        except _RETRYABLE_ERRORS as exc:
            log.warning(
                "openai.retry",
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
                error=type(exc).__name__,
                delay_s=delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
    return await make_call()  # final attempt; let the exception propagate


__all__ = [
    "INPUT_USD_PER_MTOK",
    "MAX_RETRIES",
    "OUTPUT_USD_PER_MTOK",
    "RETRY_BASE_DELAY_S",
    "completion_text",
    "create_completion_with_retry",
    "usage_cost_usd",
]
