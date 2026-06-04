from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anthropic

from coding_eval.rubric import complexity, diff_minimality, semantic, style, test_pass

WEIGHTS = {
    "test_pass_rate": 0.35,
    "diff_minimality": 0.15,
    "complexity_delta": 0.15,
    "style_score": 0.15,
    "semantic_score": 0.20,
}

if TYPE_CHECKING:
    from coding_eval.sandbox.runner import SandboxResult


@dataclass(frozen=True, slots=True)
class RubricScores:
    test_pass_rate: float
    diff_minimality: float
    complexity_delta: float
    style_score: float
    semantic_score: float

    @property
    def composite(self) -> float:
        return float(sum(getattr(self, k) * v for k, v in WEIGHTS.items()))


async def score(
    task_issue: str,
    patch: str,
    sandbox_result: "SandboxResult",
    repo_path: str,
    anthropic_client: anthropic.AsyncAnthropic,
    *,
    semantic_cache_path: str | None = None,
) -> RubricScores:
    from pathlib import Path

    cache = Path(semantic_cache_path) if semantic_cache_path else None

    (
        test_pass_rate,
        diff_score,
        complexity_score,
        style_score_value,
    ) = await asyncio.gather(
        asyncio.to_thread(test_pass.score, sandbox_result),
        asyncio.to_thread(diff_minimality.score, patch),
        asyncio.to_thread(complexity.score, patch, repo_path),
        asyncio.to_thread(style.score, patch, repo_path),
    )

    semantic_score_value = await semantic.score(
        task_issue,
        patch,
        anthropic_client,
        cache_path=cache,
    )

    return RubricScores(
        test_pass_rate=test_pass_rate,
        diff_minimality=diff_score,
        complexity_delta=complexity_score,
        style_score=style_score_value,
        semantic_score=semantic_score_value,
    )


__all__ = ["WEIGHTS", "RubricScores", "score"]
