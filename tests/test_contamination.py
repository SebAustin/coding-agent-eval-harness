from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from coding_eval.dataset.contamination import (
    CONTAMINATION_THRESHOLD,
    EMBEDDING_DIM,
    batch_check,
    compute_contamination,
    cosine_similarity_matrix,
    embed_text,
    load_swebench_embeddings,
)
from coding_eval.dataset.schema import Task

EMBEDDINGS_PATH = Path("data/contamination/swebench_train_embeddings.npz")
HTTPX_001_BODY = (
    "When using a MockTransport in tests, response.elapsed is None instead of a "
    "timedelta. Expected: a zero or near-zero timedelta. Steps: see linked test."
)


class _FakeModel:
    def __init__(self, vectors: np.ndarray) -> None:
        arr = np.asarray(vectors, dtype=np.float32)
        self._vectors = arr.reshape(1, -1) if arr.ndim == 1 else arr

    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool = False,
    ) -> np.ndarray:
        del normalize_embeddings
        if self._vectors.shape[0] == 1:
            return np.repeat(self._vectors, len(texts), axis=0)
        return self._vectors[: len(texts)]


def _random_unit_vectors(n: int, dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    return raw / norms


@pytest.fixture
def mock_corpus() -> np.ndarray:
    return _random_unit_vectors(10, EMBEDDING_DIM, seed=42)


def test_load_swebench_embeddings_from_npz(tmp_path: Path) -> None:
    path = tmp_path / "train.npz"
    corpus = _random_unit_vectors(5, EMBEDDING_DIM, seed=1)
    np.savez_compressed(path, embeddings=corpus)
    loaded = load_swebench_embeddings(str(path))
    np.testing.assert_array_equal(loaded, corpus)


def test_load_swebench_embeddings_rejects_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.npz"
    np.savez_compressed(path, vectors=np.zeros((2, EMBEDDING_DIM), dtype=np.float32))
    with pytest.raises(ValueError, match='key "embeddings"'):
        load_swebench_embeddings(str(path))


def test_load_swebench_embeddings_rejects_invalid_shape(tmp_path: Path) -> None:
    path = tmp_path / "bad.npz"
    np.savez_compressed(path, embeddings=np.array([1.0, 2.0, 3.0], dtype=np.float32))
    with pytest.raises(ValueError, match="2D"):
        load_swebench_embeddings(str(path))


def test_load_swebench_embeddings_rejects_wrong_dim(tmp_path: Path) -> None:
    path = tmp_path / "wrong_dim.npz"
    np.savez_compressed(path, embeddings=np.zeros((3, 128), dtype=np.float32))
    with pytest.raises(ValueError, match="384"):
        load_swebench_embeddings(str(path))


def test_copy_of_corpus_item_is_contaminated(mock_corpus: np.ndarray) -> None:
    copy_vec = mock_corpus[3].copy()
    fake = _FakeModel(copy_vec)
    is_cont, sim = compute_contamination("duplicate issue body", mock_corpus, fake)  # type: ignore[arg-type]
    assert sim == pytest.approx(1.0, abs=1e-5)
    assert is_cont is True


def test_unrelated_sentence_not_contaminated(mock_corpus: np.ndarray) -> None:
    unrelated = _random_unit_vectors(1, EMBEDDING_DIM, seed=99)[0]
    fake = _FakeModel(unrelated)
    is_cont, sim = compute_contamination("totally unrelated text", mock_corpus, fake)  # type: ignore[arg-type]
    assert sim < CONTAMINATION_THRESHOLD
    assert sim == pytest.approx(0.1, abs=0.15)
    assert is_cont is False


def test_batch_check_length(mock_corpus: np.ndarray) -> None:
    tasks = [
        Task(
            task_id=f"t-{i}",
            repo="o/r",
            base_commit="abc",
            issue_number=i,
            issue_title="title",
            issue_body="body",
            test_files=["tests/test_x.py"],
        )
        for i in range(4)
    ]
    vecs = _random_unit_vectors(4, EMBEDDING_DIM, seed=7)
    fake = _FakeModel(vecs)
    results = batch_check(tasks, mock_corpus, fake)  # type: ignore[arg-type]
    assert len(results) == len(tasks)
    assert all(isinstance(flag, bool) and isinstance(score, float) for flag, score in results)


def test_batch_check_empty() -> None:
    assert batch_check([], np.zeros((0, EMBEDDING_DIM), dtype=np.float32), _FakeModel(np.zeros(384))) == []  # type: ignore[arg-type]


def test_embed_text_l2_normalizes() -> None:
    raw = np.array([3.0, 4.0] + [0.0] * (EMBEDDING_DIM - 2), dtype=np.float32)
    fake = _FakeModel(raw.reshape(1, -1))
    vec = embed_text("x", fake)  # type: ignore[arg-type]
    assert vec.shape == (EMBEDDING_DIM,)
    assert vec[:2] == pytest.approx([0.6, 0.8], abs=1e-5)
    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)


def test_embed_text_zero_vector() -> None:
    fake = _FakeModel(np.zeros(EMBEDDING_DIM, dtype=np.float32))
    vec = embed_text("x", fake)  # type: ignore[arg-type]
    assert np.all(vec == 0.0)


def test_cosine_similarity_matrix_vectorized(mock_corpus: np.ndarray) -> None:
    query = mock_corpus[0]
    sims = cosine_similarity_matrix(query, mock_corpus)
    assert sims.shape == (mock_corpus.shape[0],)
    assert float(sims[0]) == pytest.approx(1.0, abs=1e-5)


def test_compute_contamination_empty_corpus() -> None:
    fake = _FakeModel(np.ones(EMBEDDING_DIM, dtype=np.float32))
    is_cont, sim = compute_contamination("x", np.zeros((0, EMBEDDING_DIM), dtype=np.float32), fake)  # type: ignore[arg-type]
    assert is_cont is False
    assert sim == 0.0


def test_cosine_similarity_zero_query(mock_corpus: np.ndarray) -> None:
    sims = cosine_similarity_matrix(np.zeros(EMBEDDING_DIM, dtype=np.float32), mock_corpus)
    assert np.all(sims == 0.0)


def test_cosine_similarity_empty_corpus() -> None:
    query = _random_unit_vectors(1, EMBEDDING_DIM, seed=0)[0]
    sims = cosine_similarity_matrix(query, np.zeros((0, EMBEDDING_DIM), dtype=np.float32))
    assert sims.shape == (0,)


def test_compute_contamination_non_finite_max(monkeypatch: pytest.MonkeyPatch) -> None:
    def _nan_sims(
        query: np.ndarray,
        corpus: np.ndarray,
    ) -> np.ndarray:
        del query, corpus
        return np.array([np.nan], dtype=np.float32)

    monkeypatch.setattr(
        "coding_eval.dataset.contamination.cosine_similarity_matrix",
        _nan_sims,
    )
    fake = _FakeModel(np.ones(EMBEDDING_DIM, dtype=np.float32))
    is_cont, sim = compute_contamination("x", np.ones((1, EMBEDDING_DIM), dtype=np.float32), fake)  # type: ignore[arg-type]
    assert is_cont is False
    assert sim == 0.0


def test_batch_check_non_finite_max() -> None:
    tasks = [
        Task(
            task_id="t-0",
            repo="o/r",
            base_commit="abc",
            issue_number=0,
            issue_title="title",
            issue_body="body",
            test_files=["tests/test_x.py"],
        ),
    ]
    corpus = _random_unit_vectors(3, EMBEDDING_DIM, seed=1)
    corpus[1, :] = np.nan
    fake = _FakeModel(_random_unit_vectors(1, EMBEDDING_DIM, seed=2)[0])
    results = batch_check(tasks, corpus, fake)  # type: ignore[arg-type]
    assert len(results) == 1
    assert results[0][0] is False
    assert np.isfinite(results[0][1])


@pytest.mark.skipif(not EMBEDDINGS_PATH.exists(), reason="Run precompute_contamination.py")
def test_httpx_001_not_contaminated() -> None:
    from sentence_transformers import SentenceTransformer

    from coding_eval.dataset.contamination import MODEL_NAME

    try:
        model = SentenceTransformer(MODEL_NAME)
    except Exception:
        pytest.skip("SentenceTransformer model unavailable offline")

    corpus = load_swebench_embeddings(str(EMBEDDINGS_PATH))
    is_cont, sim = compute_contamination(HTTPX_001_BODY, corpus, model)
    assert is_cont is False
    assert sim < CONTAMINATION_THRESHOLD
