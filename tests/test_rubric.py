from __future__ import annotations

from coding_eval.rubric.scorer import RubricScores


def test_rubric_composite_weighted_sum() -> None:
    s = RubricScores(
        test_pass_rate=1.0,
        diff_minimality=1.0,
        complexity_delta=1.0,
        style_score=1.0,
        semantic_score=1.0,
    )
    assert abs(s.composite - 1.0) < 1e-9

