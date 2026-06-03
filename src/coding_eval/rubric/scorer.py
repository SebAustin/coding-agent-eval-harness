from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anthropic

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
    anthropic_client: "anthropic.AsyncAnthropic",
) -> RubricScores:
    _ = (task_issue, patch, sandbox_result, repo_path, anthropic_client)
    # Skeleton: real implementation will compute each axis and call an LLM judge.
    return RubricScores(
        test_pass_rate=0.0,
        diff_minimality=0.0,
        complexity_delta=0.0,
        style_score=0.0,
        semantic_score=0.0,
    )

