# ruff: noqa: S101, INP001, PT001, PT023, TC003, PLR2004, S106, SLF001, E501, S108, ARG002, PLC0415
"""OpenAI adapter unit tests.

Mirrors tests/test_claude_code.py one-to-one with a mocked AsyncOpenAI client (no
network). Includes the three mandatory tests from PLAN.md §7 / S15:
  - test_openai_cost_single_call: pins exact single-call cost_usd
  - test_openai_cost_sums_across_retries: pins cost as SUM across multiple calls
  - test_openai_empty_completion_yields_empty_patch: guards the empty-choices degrade path

Also covers S6/S7 registry and key-plumbing assertions.

Note: ``openai==1.57.4`` + ``httpx==0.28.1`` are fully compatible — the
``proxies`` kwarg was removed from httpx 0.28 and openai stopped passing it in
~1.55.3. Construction is now real; tests replace ``adapter._client`` after
construction to inject mocks, consistent with ``test_claude_code.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from git import Repo

from coding_eval.agents import AGENT_REGISTRY, get_adapter
from coding_eval.agents._openai_client import INPUT_USD_PER_MTOK, OUTPUT_USD_PER_MTOK
from coding_eval.agents.openai_adapter import OpenAIAdapter
from coding_eval.dataset.schema import Task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task() -> Task:
    return Task(
        task_id="t1",
        repo="Textualize/rich",
        base_commit="abc123456789",
        issue_number=1,
        issue_title="Fix bug",
        issue_body="Something broke in rich/pretty.py",
        test_files=["tests/test_pretty.py"],
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    tests = repo / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "pretty.py").write_text("value = 1\n", encoding="utf-8")
    (tests / "test_pretty.py").write_text("from rich import pretty\n", encoding="utf-8")
    git_repo = Repo.init(repo)
    git_repo.index.add(["rich/__init__.py", "rich/pretty.py", "tests/test_pretty.py"])
    git_repo.index.commit("init")
    return repo


def _completion(
    text: str,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> MagicMock:
    """Build a mock ChatCompletion with the given text and token counts."""
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=text))],
        usage=MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _empty_completion() -> MagicMock:
    """No choices at all -> completion_text returns "" -> empty-patch path."""
    return MagicMock(choices=[], usage=MagicMock(prompt_tokens=10, completion_tokens=0))


def _make_adapter(
    side_effect: list[MagicMock] | None = None, return_value: MagicMock | None = None
) -> OpenAIAdapter:
    """Create an OpenAIAdapter with a real client construction, then replace _client."""
    adapter = OpenAIAdapter(api_key="test-key")
    mock_client = AsyncMock()
    if side_effect is not None:
        mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)
    elif return_value is not None:
        mock_client.chat.completions.create = AsyncMock(return_value=return_value)
    else:
        mock_client.chat.completions.create = AsyncMock()
    adapter._client = mock_client
    return adapter


# ---------------------------------------------------------------------------
# Registry / key-plumbing assertions (S6, S7)
# ---------------------------------------------------------------------------


def test_openai_registered_in_agent_registry() -> None:
    assert "openai" in AGENT_REGISTRY


def test_get_adapter_openai_with_explicit_key() -> None:
    adapter = get_adapter("openai", api_key="test-x")
    assert isinstance(adapter, OpenAIAdapter)


def test_get_adapter_openai_without_key_constructs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No explicit key AND no OPENAI_API_KEY in env: the adapter must still
    # construct (the OpenAI client is built lazily, so the missing-key error is
    # deferred to solve time — matching the Anthropic adapter's behavior).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = get_adapter("openai")
    assert isinstance(adapter, OpenAIAdapter)


# ---------------------------------------------------------------------------
# Happy path: patch applies on first try (S9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_no_retry_when_patch_applies(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = _make_adapter(return_value=_completion(good_patch))

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    adapter._client.chat.completions.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# Apply-check retry: bad patch -> good patch (S9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_retry_on_apply_check_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = _make_adapter(side_effect=[_completion(bad_patch), _completion(good_patch)])

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    assert adapter._client.chat.completions.create.await_count == 2


# ---------------------------------------------------------------------------
# Exhausted retries: all patches fail apply-check -> empty patch (S9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_rejects_retry_patch_that_fails_apply_check(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    still_bad_patch = (
        "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-wrong\n+value = 2\n"
    )
    third_bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-nope\n+value = 2\n"

    adapter = _make_adapter(
        side_effect=[
            _completion(bad_patch),
            _completion(still_bad_patch),
            _completion(third_bad_patch),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == ""
    assert adapter._client.chat.completions.create.await_count == 3


# ---------------------------------------------------------------------------
# Format-reprompt: malformed -> good via fixup (S9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_format_reprompt_when_extract_empty(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    malformed = (
        "The fix removes the early return.\n\n"
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1 +1 @@\n"
        "broken-line-without-prefix\n"
    )
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = _make_adapter(side_effect=[_completion(malformed), _completion(good_patch)])

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    assert adapter._client.chat.completions.create.await_count == 2
    assert "--- format fixup ---" in result.raw_response


# ---------------------------------------------------------------------------
# Empty completion guard: choices=[] -> empty patch, no crash (S9, defect 6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_empty_completion_yields_empty_patch(tmp_path: Path) -> None:
    """Client returns choices=[] -> result.patch == "", no exception raised."""
    repo = _make_repo(tmp_path)

    adapter = _make_adapter(return_value=_empty_completion())

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == ""
    assert adapter._client.chat.completions.create.await_count == 1


# ---------------------------------------------------------------------------
# S15(a): single-call cost assertion — exact value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_cost_single_call(tmp_path: Path) -> None:
    """Happy path, one call: cost_usd == (prompt*INPUT + completion*OUTPUT)/1e6 exactly."""
    repo = _make_repo(tmp_path)
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    prompt_tokens = 100
    completion_tokens = 50

    adapter = _make_adapter(
        return_value=_completion(
            good_patch, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )

    result = await adapter.solve(_task(), str(repo))

    expected = (
        prompt_tokens * INPUT_USD_PER_MTOK + completion_tokens * OUTPUT_USD_PER_MTOK
    ) / 1_000_000
    assert result.patch == good_patch
    assert result.cost_usd == pytest.approx(expected)


# ---------------------------------------------------------------------------
# S15(b): multi-call cost assertion — cost is the SUM across all calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_cost_sums_across_retries(tmp_path: Path) -> None:
    """Retry path (2 calls): cost_usd == sum of each call's increment.

    Asserts the sum is strictly greater than any single call's increment, proving
    it is a sum and not a single-call value.
    """
    repo = _make_repo(tmp_path)
    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    # Use distinct token counts to make the sum unambiguous.
    call1_prompt, call1_completion = 120, 60
    call2_prompt, call2_completion = 80, 40

    adapter = _make_adapter(
        side_effect=[
            _completion(bad_patch, prompt_tokens=call1_prompt, completion_tokens=call1_completion),
            _completion(good_patch, prompt_tokens=call2_prompt, completion_tokens=call2_completion),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    inc1 = (call1_prompt * INPUT_USD_PER_MTOK + call1_completion * OUTPUT_USD_PER_MTOK) / 1_000_000
    inc2 = (call2_prompt * INPUT_USD_PER_MTOK + call2_completion * OUTPUT_USD_PER_MTOK) / 1_000_000
    expected_total = inc1 + inc2

    assert result.patch == good_patch
    assert result.cost_usd == pytest.approx(expected_total)
    # Prove it is the SUM, not just one call's cost.
    assert result.cost_usd > inc1
    assert result.cost_usd > inc2


# ---------------------------------------------------------------------------
# name() method (openai_adapter.py line 47)
# ---------------------------------------------------------------------------


def test_openai_adapter_name() -> None:
    """OpenAIAdapter.name() returns the agent_id string."""
    adapter = OpenAIAdapter(api_key="test-key")
    assert adapter.name() == "openai"


# ---------------------------------------------------------------------------
# Format-fixup after retry: solver line 149 (_solver.py)
#
# Scenario: initial patch fails apply-check; retry response is malformed
# (looks like a diff attempt but extraction fails); format-fixup reprompt on
# the retry response produces a good patch.  This exercises the branch at
# _solver.py line 149 that appends "--- format fixup (retry N) ---" to raw_log.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_format_fixup_after_retry(tmp_path: Path) -> None:
    """Bad initial patch -> retry with malformed -> fixup reprompt -> good patch.

    Covers _solver.py line 149: raw_log.append(f"--- format fixup (retry {n}) ---").
    """
    repo = _make_repo(tmp_path)
    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    # Retry produces malformed (looks like a diff attempt, but extraction fails)
    malformed_retry = (
        "Here is the fix:\n\n"
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1 +1 @@\n"
        "broken-line-without-prefix\n"
    )
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    # Calls: (1) bad_patch, (2) malformed_retry, (3) good_patch from fixup reprompt
    adapter = _make_adapter(
        side_effect=[
            _completion(bad_patch),
            _completion(malformed_retry),
            _completion(good_patch),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    assert adapter._client.chat.completions.create.await_count == 3
    # The fixup-after-retry marker must appear in the raw log
    assert "--- format fixup (retry 2) ---" in result.raw_response


# ---------------------------------------------------------------------------
# Fallback_raws path: solver lines 201-210 (_extract_with_format_fixup)
#
# Scenario: initial response is malformed, FORMAT_REPROMPT response also
# malformed, FORMAT_REPROMPT_STRICT response has NO diff marker so the loop
# breaks early (line 202), then fallback_raws=[original_malformed] is tried
# and also fails (extraction returns ""), so the function returns ("", cost, log).
# This hits lines 201-202 (break) and 204-210 (fallback loop + empty return).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_fallback_raws_all_fail_yields_empty_patch(tmp_path: Path) -> None:
    """All format reprompts fail AND fallback raws are also unextractable -> empty patch.

    Covers _solver.py lines 201-202 (break on no diff marker) and lines 204-210
    (fallback loop exhausted, return empty string).
    """
    repo = _make_repo(tmp_path)
    # All three responses look like diffs but none are extractable
    malformed = (
        "Here is the fix:\n\n"
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1 +1 @@\n"
        "broken-line-without-prefix\n"
    )
    # Second reprompt response: no diff marker at all -> triggers break at line 202
    no_diff_marker = "I am unable to produce a valid diff for this issue."

    # Calls: (1) malformed initial, (2) FORMAT_REPROMPT fixup -> malformed again,
    # (3) FORMAT_REPROMPT_STRICT fixup -> no diff marker (triggers break)
    adapter = _make_adapter(
        side_effect=[
            _completion(malformed),
            _completion(malformed),
            _completion(no_diff_marker),
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    # All attempts fail: empty patch returned (no crash)
    assert result.patch == ""
    # 1 initial + 2 format-fixup reprompts = 3 calls
    assert adapter._client.chat.completions.create.await_count == 3


# ---------------------------------------------------------------------------
# Fallback_raws SUCCESS path: solver lines 207-208
#
# Scenario: initial patch is bad (fails apply-check); retry response is
# malformed (looks like diff but not extractable); FORMAT_REPROMPT fixup also
# malformed; FORMAT_REPROMPT_STRICT fixup has no diff marker (break); then the
# fallback loop tries fallback_raws=[retry_malformed, original_bad_patch] —
# the original bad_patch IS extractable so line 207-208 is hit and the fallback
# patch is returned.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_fallback_raws_extractable_fallback_returned(tmp_path: Path) -> None:
    """Format fixup fails entirely; fallback_raws contain an extractable patch.

    Covers _solver.py lines 207-208: the fallback loop finds an extractable
    patch in fallback_raws and returns it via the agent.extract_fallback_raw path.

    Flow:
      Call 1: bad_patch (fails apply-check, attempt 0 of 3)
      Call 2: malformed_retry (needs format fixup)
      Call 3: FORMAT_REPROMPT -> still malformed
      Call 4: FORMAT_REPROMPT_STRICT -> no diff marker (break)
              -> fallback finds bad_patch from fallback_raws -> extract_fallback_raw path
              -> bad_patch fails apply-check again (attempt 1 of 3)
      Call 5: good_patch (second retry, applies cleanly)
    """
    repo = _make_repo(tmp_path)
    bad_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value\n+value = 2\n"
    malformed_retry = (
        "Here is the corrected diff:\n\n"
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1 +1 @@\n"
        "broken-line-without-prefix\n"
    )
    no_diff_marker = "Sorry, I cannot produce a valid diff."
    good_patch = "--- a/rich/pretty.py\n+++ b/rich/pretty.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    adapter = _make_adapter(
        side_effect=[
            _completion(bad_patch),  # call 1: initial, fails apply
            _completion(malformed_retry),  # call 2: retry, malformed -> fixup loop
            _completion(malformed_retry),  # call 3: FORMAT_REPROMPT -> still malformed
            _completion(no_diff_marker),  # call 4: FORMAT_REPROMPT_STRICT -> break
            # fallback extracts bad_patch (extract_fallback_raw), fails apply again
            _completion(good_patch),  # call 5: second retry -> good patch
        ],
    )

    result = await adapter.solve(_task(), str(repo))

    assert result.patch == good_patch
    assert adapter._client.chat.completions.create.await_count == 5
