from __future__ import annotations

import numpy as np

from coding_eval.dataset.contamination import (
    CONTAMINATION_THRESHOLD,
    _cosine_max,
    compute_contamination,
    load_swebench_embeddings,
)


class _FakeModel:
    def __init__(self, vec: np.ndarray) -> None:
        self._vec = vec

    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool = False,
    ) -> np.ndarray:
        del texts, normalize_embeddings
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


def test_load_swebench_embeddings_rejects_invalid_shape(tmp_path: object) -> None:
    from pathlib import Path

    p = Path(str(tmp_path)) / "bad.npy"
    np.save(p, np.array([1.0, 2.0, 3.0]))
    try:
        load_swebench_embeddings(str(p))
    except ValueError as exc:
        assert "2D" in str(exc)
    else:
        msg = "expected ValueError"
        raise AssertionError(msg)


def test_cosine_max_zero_vector() -> None:
    emb = np.array([[1.0, 0.0]], dtype=np.float32)
    q = np.array([0.0, 0.0], dtype=np.float32)
    assert _cosine_max(q, emb) == 0.0
