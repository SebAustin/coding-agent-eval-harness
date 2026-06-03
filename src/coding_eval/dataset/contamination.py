from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from coding_eval.dataset.schema import Task

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
CONTAMINATION_THRESHOLD = 0.85


def load_swebench_embeddings(path: str) -> NDArray[np.float32]:
    with np.load(path) as data:
        if "embeddings" not in data:
            msg = 'NPZ file must contain key "embeddings"'
            raise ValueError(msg)
        arr = np.asarray(data["embeddings"], dtype=np.float32)
    if arr.ndim != 2:
        msg = f"Expected 2D embeddings array, got shape {arr.shape!r}"
        raise ValueError(msg)
    if arr.shape[1] != EMBEDDING_DIM:
        msg = f"Expected embedding dim {EMBEDDING_DIM}, got {arr.shape[1]}"
        raise ValueError(msg)
    return arr


def _l2_normalize(vec: NDArray[np.float32]) -> NDArray[np.float32]:
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm == 0.0:
        return np.zeros_like(vec)
    return (vec / norm).astype(np.float32)


def _l2_normalize_rows(mat: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return np.divide(mat, norms, out=np.zeros_like(mat), where=(norms != 0))


def embed_text(text: str, model: SentenceTransformer) -> NDArray[np.float32]:
    encoded = model.encode([text], normalize_embeddings=False)
    vec = np.asarray(encoded[0], dtype=np.float32)
    return _l2_normalize(vec)


def cosine_similarity_matrix(
    query: NDArray[np.float32],
    corpus: NDArray[np.float32],
) -> NDArray[np.float32]:
    c = np.asarray(corpus, dtype=np.float32)
    if c.size == 0:
        return np.array([], dtype=np.float32)
    q = _l2_normalize(np.asarray(query, dtype=np.float32).reshape(-1))
    c = _l2_normalize_rows(c)
    sims: NDArray[np.float32] = c @ q
    return sims


def compute_contamination(
    issue_body: str,
    swebench_embeddings: NDArray[np.float32],
    model: SentenceTransformer,
) -> tuple[bool, float]:
    """Returns (is_contaminated, max_cosine_similarity)."""
    query = embed_text(issue_body, model)
    sims = cosine_similarity_matrix(query, swebench_embeddings)
    if sims.size == 0:
        return False, 0.0
    max_sim = float(np.max(sims))
    if not np.isfinite(max_sim):
        max_sim = 0.0
    return max_sim > CONTAMINATION_THRESHOLD, max_sim


def batch_check(
    tasks: list[Task],
    swebench_embeddings: NDArray[np.float32],
    model: SentenceTransformer,
) -> list[tuple[bool, float]]:
    if not tasks:
        return []

    texts = [task.issue_body for task in tasks]
    encoded = model.encode(texts, normalize_embeddings=False)
    queries = _l2_normalize_rows(np.asarray(encoded, dtype=np.float32))
    corpus = _l2_normalize_rows(swebench_embeddings)
    sims: NDArray[np.float32] = queries @ corpus.T
    max_sims = np.max(sims, axis=1) if sims.size else np.zeros(len(tasks), dtype=np.float32)

    results: list[tuple[bool, float]] = []
    for max_sim in max_sims:
        score = float(max_sim)
        if not np.isfinite(score):
            score = 0.0
        results.append((score > CONTAMINATION_THRESHOLD, score))
    return results


__all__ = [
    "CONTAMINATION_THRESHOLD",
    "EMBEDDING_DIM",
    "MODEL_NAME",
    "batch_check",
    "compute_contamination",
    "cosine_similarity_matrix",
    "embed_text",
    "load_swebench_embeddings",
]
