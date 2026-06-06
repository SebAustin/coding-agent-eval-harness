from __future__ import annotations

import anthropic
import httpx
import pytest

from coding_eval.agents import _common
from coding_eval.agents._common import create_message_with_retry


def _response(status: int) -> httpx.Response:
    return httpx.Response(
        status,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


@pytest.mark.asyncio
async def test_retries_transient_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_common, "RETRY_BASE_DELAY_S", 0.0)
    calls = {"n": 0}
    sentinel = object()

    async def make_call() -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise anthropic.RateLimitError("rate limited", response=_response(429), body=None)
        if calls["n"] == 2:
            raise anthropic.InternalServerError("boom", response=_response(503), body=None)
        return sentinel

    result = await create_message_with_retry(make_call)  # type: ignore[arg-type]

    assert result is sentinel
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_non_retryable_error_propagates_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_common, "RETRY_BASE_DELAY_S", 0.0)
    calls = {"n": 0}

    async def make_call() -> object:
        calls["n"] += 1
        raise anthropic.BadRequestError("bad", response=_response(400), body=None)

    with pytest.raises(anthropic.BadRequestError):
        await create_message_with_retry(make_call)  # type: ignore[arg-type]

    assert calls["n"] == 1  # 400 is not retried


@pytest.mark.asyncio
async def test_exhausted_retries_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_common, "RETRY_BASE_DELAY_S", 0.0)
    calls = {"n": 0}

    async def make_call() -> object:
        calls["n"] += 1
        raise anthropic.InternalServerError("down", response=_response(500), body=None)

    with pytest.raises(anthropic.InternalServerError):
        await create_message_with_retry(make_call)  # type: ignore[arg-type]

    assert calls["n"] == _common.MAX_RETRIES + 1  # retries + final attempt
