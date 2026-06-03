from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
CONTAMINATION_THRESHOLD = 0.85


def load_swebench_embeddings(path: str) -> NDArray[np.float32]:
    arr = np.load(path)
    if arr.ndim != 2:
        msg = f"Expected 2D embeddings array, got shape {arr.shape!r}"
        raise ValueError(msg)
    return np.asarray(arr, dtype=np.float32)


def _cosine_max(query_vec: NDArray[np.float32], mat: NDArray[np.float32]) -> float:
    q = query_vec.astype(np.float32, copy=False)
    q_norm = np.linalg.norm(q)
    if not np.isfinite(q_norm) or q_norm == 0:
        return 0.0
    q = q / q_norm

    m = mat.astype(np.float32, copy=False)
    m_norms = np.linalg.norm(m, axis=1, keepdims=True)
    m = np.divide(m, m_norms, out=np.zeros_like(m), where=(m_norms != 0))

    sims = m @ q
    max_sim = float(np.max(sims)) if sims.size else 0.0
    if not np.isfinite(max_sim):
        return 0.0
    return max_sim


def compute_contamination(
    issue_body: str,
    swebench_embeddings: NDArray[np.float32],
    model: SentenceTransformer,
) -> tuple[bool, float]:
    """Returns (is_contaminated, max_cosine_similarity)."""
    vec = model.encode([issue_body], normalize_embeddings=False)
    query = np.asarray(vec, dtype=np.float32)[0]
    max_sim = _cosine_max(query, swebench_embeddings)
    return (max_sim > CONTAMINATION_THRESHOLD, max_sim)

