from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import anthropic
import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = structlog.get_logger(__name__)

# Sonnet 4.5 host-side pricing (USD per million tokens). Both adapters share the
# same model and meter cost identically, so the rates live in one place.
INPUT_USD_PER_MTOK = 3.0
OUTPUT_USD_PER_MTOK = 15.0

# Transient API failures worth retrying with backoff. The agentic adapter makes
# many calls per task, so a single rate-limit or 5xx blip should not abort a solve.
MAX_RETRIES = 4
RETRY_BASE_DELAY_S = 1.0
_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,  # 429
    anthropic.InternalServerError,  # 5xx, incl. 529 overloaded
    anthropic.APIConnectionError,  # network drop / timeout
)


def usage_cost_usd(usage: anthropic.types.Usage) -> float:
    return (
        usage.input_tokens * INPUT_USD_PER_MTOK + usage.output_tokens * OUTPUT_USD_PER_MTOK
    ) / 1_000_000


def message_text(message: anthropic.types.Message) -> str:
    return "\n".join(block.text for block in message.content if block.type == "text")


async def create_message_with_retry(
    make_call: Callable[[], Awaitable[anthropic.types.Message]],
) -> anthropic.types.Message:
    """Await ``make_call`` with exponential backoff on transient API errors.

    Retries rate-limit / 5xx / connection errors up to ``MAX_RETRIES`` times,
    doubling the delay each time. Non-transient errors (bad request, auth) and the
    final attempt propagate immediately, so a real failure still surfaces.
    """
    delay = RETRY_BASE_DELAY_S
    for attempt in range(MAX_RETRIES):
        try:
            return await make_call()
        except _RETRYABLE_ERRORS as exc:
            log.warning(
                "anthropic.retry",
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
    "create_message_with_retry",
    "message_text",
    "usage_cost_usd",
]
