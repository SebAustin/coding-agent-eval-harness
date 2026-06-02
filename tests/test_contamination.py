from __future__ import annotations

import numpy as np

from coding_eval.dataset.contamination import CONTAMINATION_THRESHOLD, compute_contamination


class _FakeModel:
    def __init__(self, vec: np.ndarray) -> None:
        self._vec = vec

    def encode(self, texts: list[str], normalize_embeddings: bool = False) -> np.ndarray:  # noqa: ARG002
        return np.stack([self._vec], axis=0)


def test_contamination_threshold_logic() -> None:
    emb = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    fake = _FakeModel(q)
    is_cont, sim = compute_contamination("x", emb, fake)  # type: ignore[arg-type]
    assert sim >= CONTAMINATION_THRESHOLD
    assert is_cont is True

