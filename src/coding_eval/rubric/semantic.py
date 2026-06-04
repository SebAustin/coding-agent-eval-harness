from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import anthropic

MODEL_ID = "claude-sonnet-4-5-20251022"
DEFAULT_CACHE_PATH = Path("data/semantic_cache.sqlite")

SYSTEM_PROMPT = (
    "You are a code review judge. Rate whether the patch correctly and "
    "completely addresses the issue on a scale 0.0-1.0. Return ONLY a JSON object: "
    '{"score": float, "reasoning": str}.'
)

_JSON_RE = re.compile(r"\{[^{}]*\"score\"[^{}]*\}", re.DOTALL)


def _cache_key(issue_body: str, patch: str) -> str:
    material = issue_body + patch[:500]
    return hashlib.sha256(material.encode()).hexdigest()


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


def _parse_score_from_text(text: str) -> float:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
        raw = float(payload["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        match = _JSON_RE.search(stripped)
        if match is None:
            return 0.0
        payload = json.loads(match.group(0))
        raw = float(payload["score"])
    return max(0.0, min(1.0, raw))


def _message_text(message: anthropic.types.Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


async def score(
    issue_body: str,
    patch: str,
    client: anthropic.AsyncAnthropic,
    *,
    cache_path: Path | None = None,
) -> float:
    path = cache_path or DEFAULT_CACHE_PATH
    key = _cache_key(issue_body, patch)
    cached = _read_cache(path, key)
    if cached is not None:
        return cached

    message = await client.messages.create(
        model=MODEL_ID,
        max_tokens=256,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Issue:\n{issue_body}\n\nPatch:\n{patch[:3000]}",
            },
        ],
    )
    result = _parse_score_from_text(_message_text(message))
    _write_cache(path, key, result)
    return result


__all__ = ["DEFAULT_CACHE_PATH", "MODEL_ID", "score"]
