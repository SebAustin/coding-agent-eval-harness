# ruff: noqa: S101, INP001, PT001, PT023, TC003, PLR2004, S106, SLF001, E501, S108, ARG002, PLC0415
"""Unit tests for _openai_client primitives.

Mirrors tests/test_agent_retry.py for the Anthropic primitives. Covers the
three branches not exercised by test_openai_adapter.py:

  - ``usage_cost_usd(None)`` — the None-usage guard (line 47)
  - ``create_completion_with_retry`` transient-error + sleep + retry path (lines 78-88)
  - ``create_completion_with_retry`` non-retryable error propagates immediately
  - ``create_completion_with_retry`` exhausted retries raise on the final attempt
"""

from __future__ import annotations

import httpx
import openai
import pytest

from coding_eval.agents import _openai_client as _oai_mod
from coding_eval.agents._openai_client import (
    INPUT_USD_PER_MTOK,
    MAX_RETRIES,
    OUTPUT_USD_PER_MTOK,
    create_completion_with_retry,
    usage_cost_usd,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _response(status: int) -> httpx.Response:
    return httpx.Response(
        status,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


# ---------------------------------------------------------------------------
# usage_cost_usd: None usage guard (line 47)
# ---------------------------------------------------------------------------


def test_usage_cost_usd_none_returns_zero() -> None:
    """usage_cost_usd(None) must return 0.0 without raising (None-guard branch)."""
    assert usage_cost_usd(None) == 0.0


def test_usage_cost_usd_normal() -> None:
    """Verify the normal formula: (prompt * INPUT + completion * OUTPUT) / 1e6."""
    from unittest.mock import MagicMock

    usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    expected = (100 * INPUT_USD_PER_MTOK + 50 * OUTPUT_USD_PER_MTOK) / 1_000_000
    assert usage_cost_usd(usage) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# create_completion_with_retry: retry backoff path (lines 78-88)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """RateLimitError (429) is retried; subsequent success is returned."""
    monkeypatch.setattr(_oai_mod, "RETRY_BASE_DELAY_S", 0.0)
    calls: list[int] = []
    sentinel = object()

    async def make_call() -> object:
        calls.append(1)
        if len(calls) == 1:
            raise openai.RateLimitError("rate limited", response=_response(429), body=None)
        return sentinel

    result = await create_completion_with_retry(make_call)  # type: ignore[arg-type]

    assert result is sentinel
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retries_internal_server_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InternalServerError (500) triggers a retry; subsequent success is returned."""
    monkeypatch.setattr(_oai_mod, "RETRY_BASE_DELAY_S", 0.0)
    calls: list[int] = []
    sentinel = object()

    async def make_call() -> object:
        calls.append(1)
        if len(calls) <= 2:
            raise openai.InternalServerError("server error", response=_response(500), body=None)
        return sentinel

    result = await create_completion_with_retry(make_call)  # type: ignore[arg-type]

    assert result is sentinel
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retries_connection_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APIConnectionError triggers a retry; subsequent success is returned."""
    monkeypatch.setattr(_oai_mod, "RETRY_BASE_DELAY_S", 0.0)
    calls: list[int] = []
    sentinel = object()

    async def make_call() -> object:
        calls.append(1)
        if len(calls) == 1:
            raise openai.APIConnectionError(message="connection dropped", request=_request())
        return sentinel

    result = await create_completion_with_retry(make_call)  # type: ignore[arg-type]

    assert result is sentinel
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retries_timeout_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APITimeoutError triggers a retry; subsequent success is returned."""
    monkeypatch.setattr(_oai_mod, "RETRY_BASE_DELAY_S", 0.0)
    calls: list[int] = []
    sentinel = object()

    async def make_call() -> object:
        calls.append(1)
        if len(calls) == 1:
            raise openai.APITimeoutError(request=_request())
        return sentinel

    result = await create_completion_with_retry(make_call)  # type: ignore[arg-type]

    assert result is sentinel
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_non_retryable_error_propagates_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 BadRequestError is not retried — it propagates on the first call."""
    monkeypatch.setattr(_oai_mod, "RETRY_BASE_DELAY_S", 0.0)
    calls: list[int] = []

    async def make_call() -> object:
        calls.append(1)
        raise openai.BadRequestError("bad request", response=_response(400), body=None)

    with pytest.raises(openai.BadRequestError):
        await create_completion_with_retry(make_call)  # type: ignore[arg-type]

    assert len(calls) == 1  # 400 is not retried


@pytest.mark.asyncio
async def test_exhausted_retries_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """When all retry attempts are exhausted the final exception propagates."""
    monkeypatch.setattr(_oai_mod, "RETRY_BASE_DELAY_S", 0.0)
    calls: list[int] = []

    async def make_call() -> object:
        calls.append(1)
        raise openai.InternalServerError("down", response=_response(500), body=None)

    with pytest.raises(openai.InternalServerError):
        await create_completion_with_retry(make_call)  # type: ignore[arg-type]

    # MAX_RETRIES loop attempts + 1 final attempt
    assert len(calls) == MAX_RETRIES + 1
