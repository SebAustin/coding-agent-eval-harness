from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Literal

import anthropic
import structlog

from coding_eval.models import DEFAULT_JUDGE_MODEL
from coding_eval.rubric.test_output import pytest_has_syntax_error, target_tests_failed

log = structlog.get_logger(__name__)

MODEL_ID = DEFAULT_JUDGE_MODEL
DEFAULT_CACHE_PATH = Path("data/semantic_cache.sqlite")
CACHE_VERSION = "v6"

ParseMethod = Literal["json", "regex", "reprompt_json", "reprompt_regex", "failed"]

_SCORE_FIELD_RE = re.compile(r'"score"\s*:\s*([0-9]+(?:\.[0-9]+)?)')

SYSTEM_PROMPT = (
    "You are a code review judge. Rate whether the patch correctly and "
    "completely addresses the issue on a scale 0.0-1.0. "
    "When test results are provided, use them: a partial pass (some tests pass, "
    "target test fails) should score between 0.1 and 0.5 depending on how close "
    "the fix is; when all sandbox tests pass, score >= 0.7 unless the patch "
    "clearly does not address the issue. "
    "Patches that only modify test files are invalid — score 0.0. "
    "Return ONLY a single-line JSON object with no markdown fences and no prose "
    "before or after. The reasoning field must be one line (no embedded newlines): "
    '{"score": float, "reasoning": str}.'
)

JUDGE_REPROMPT = (
    "Your previous reply was not valid JSON. Reply with ONLY a single-line JSON object: "
    '{"score": 0.0, "reasoning": "brief one-line reason"}'
)


def _cache_key(
    issue_title: str,
    issue_body: str,
    patch: str,
    *,
    test_pass_rate: float | None = None,
    test_only_patch: bool = False,
    test_files: tuple[str, ...] = (),
) -> str:
    test_hint = "" if test_pass_rate is None else f":tpr={test_pass_rate:.4f}"
    cheat_hint = ":test_only" if test_only_patch else ""
    files_hint = f":tf={','.join(sorted(test_files))}" if test_files else ""
    material = (
        f"{CACHE_VERSION}:{issue_title}:{issue_body}:{patch[:500]}"
        f"{test_hint}{cheat_hint}{files_hint}"
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _calibrate_score(
    judge_score: float,
    *,
    test_pass_rate: float | None,
    test_output_tail: str,
    test_files: list[str],
) -> float:
    score = judge_score
    if pytest_has_syntax_error(test_output_tail):
        return min(score, 0.05)
    if test_pass_rate is not None and test_pass_rate < 1.0:
        if target_tests_failed(test_files, test_output_tail):
            return min(score, 0.35)
        return min(score, 0.55)
    return score


def _ensure_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_scores (
            cache_key TEXT PRIMARY KEY,
            score REAL NOT NULL
        )
        """,
    )
    conn.commit()


def _read_cache(cache_path: Path, cache_key: str) -> float | None:
    if not cache_path.exists():
        return None
    with sqlite3.connect(cache_path) as conn:
        _ensure_cache_table(conn)
        row = conn.execute(
            "SELECT score FROM semantic_scores WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if row is None:
        return None
    return float(row[0])


def _write_cache(cache_path: Path, cache_key: str, value: float) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cache_path) as conn:
        _ensure_cache_table(conn)
        conn.execute(
            """
            INSERT INTO semantic_scores (cache_key, score)
            VALUES (?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET score = excluded.score
            """,
            (cache_key, value),
        )
        conn.commit()


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _parse_score_from_text(text: str) -> float | None:
    stripped = _strip_markdown_fences(text.strip())
    raw_score = _extract_score_json(stripped)
    if raw_score is not None:
        return _clamp_score(raw_score)
    regex_score = _extract_score_regex(stripped)
    if regex_score is not None:
        log.info("semantic.parse_regex_fallback")
        return regex_score
    return None


def _strip_markdown_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_score_json(text: str) -> float | None:
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start == -1:
            break
        try:
            payload, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(payload, dict) and "score" in payload:
            try:
                return float(payload["score"])
            except (TypeError, ValueError):
                return None
        idx = start + max(end, 1)
    return None


def _extract_score_regex(text: str) -> float | None:
    match = _SCORE_FIELD_RE.search(text)
    if match is None:
        return None
    try:
        return _clamp_score(float(match.group(1)))
    except ValueError:
        return None


def _message_text(message: anthropic.types.Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


def _parse_with_method(text: str, *, via_reprompt: bool) -> tuple[float | None, ParseMethod | None]:
    stripped = _strip_markdown_fences(text.strip())
    json_score = _extract_score_json(stripped)
    if json_score is not None:
        method: ParseMethod = "reprompt_json" if via_reprompt else "json"
        return _clamp_score(json_score), method
    regex_score = _extract_score_regex(stripped)
    if regex_score is not None:
        if not via_reprompt:
            log.info("semantic.parse_regex_fallback")
        method = "reprompt_regex" if via_reprompt else "regex"
        return regex_score, method
    return None, None


async def _call_judge(
    client: anthropic.AsyncAnthropic,
    messages: list[dict[str, str]],
) -> str:
    message = await client.messages.create(
        model=MODEL_ID,
        max_tokens=256,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=messages,  # type: ignore[arg-type]
    )
    return _message_text(message)


async def score(
    issue_body: str,
    patch: str,
    client: anthropic.AsyncAnthropic,
    *,
    issue_title: str = "",
    cache_path: Path | None = None,
    test_pass_rate: float | None = None,
    test_output_tail: str = "",
    test_only_patch: bool = False,
    test_files: list[str] | None = None,
) -> float:
    if not patch.strip():
        return 0.0
    if test_only_patch:
        return 0.0

    files = tuple(test_files or ())
    path = cache_path or DEFAULT_CACHE_PATH
    key = _cache_key(
        issue_title,
        issue_body,
        patch,
        test_pass_rate=test_pass_rate,
        test_only_patch=test_only_patch,
        test_files=files,
    )
    cached = _read_cache(path, key)
    if cached is not None:
        return cached

    issue_parts = []
    if issue_title.strip():
        issue_parts.append(f"Title: {issue_title}")
    issue_parts.append(f"Body:\n{issue_body}")

    user_parts = ["Issue:\n" + "\n\n".join(issue_parts), f"Patch:\n{patch[:3000]}"]
    if test_pass_rate is not None:
        user_parts.append(f"Sandbox test pass rate: {test_pass_rate:.2f}")
        if test_pass_rate >= 1.0:
            user_parts.append("All sandbox tests passed.")
    if test_output_tail.strip():
        user_parts.append(f"Pytest output (tail):\n{test_output_tail[-1500:]}")

    messages: list[dict[str, str]] = [
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    raw_text = await _call_judge(client, messages)
    parsed, method = _parse_with_method(raw_text, via_reprompt=False)

    if parsed is None:
        log.warning("semantic.parse_failed", raw_preview=raw_text[:300])
        log.info("semantic.reprompt")
        messages.append({"role": "assistant", "content": raw_text})
        messages.append({"role": "user", "content": JUDGE_REPROMPT})
        retry_text = await _call_judge(client, messages)
        parsed, method = _parse_with_method(retry_text, via_reprompt=True)
        if parsed is None:
            log.warning("semantic.parse_failed", raw_preview=retry_text[:300])
            method = "failed"

    if parsed is None:
        result = 0.0
    else:
        result = _calibrate_score(
            parsed,
            test_pass_rate=test_pass_rate,
            test_output_tail=test_output_tail,
            test_files=list(files),
        )
        log.info(
            "semantic.scored",
            score=result,
            judge_score=parsed,
            test_pass_rate=test_pass_rate,
            parse_method=method,
        )

    _write_cache(path, key, result)
    return result


__all__ = ["DEFAULT_CACHE_PATH", "JUDGE_REPROMPT", "MODEL_ID", "score"]
