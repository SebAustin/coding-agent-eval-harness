from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import typer
from datasets import concatenate_datasets, load_dataset, load_dataset_builder
from sentence_transformers import SentenceTransformer

from coding_eval.dataset.contamination import EMBEDDING_DIM, MODEL_NAME

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

log = structlog.get_logger(__name__)

DEFAULT_OUTPUT = Path("data/contamination/swebench_train_embeddings.npz")
DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DATASET_SPLIT = "train"

app = typer.Typer(add_completion=False)


def _embedding_text(instance_id: str, problem_statement: str) -> str:
    return f"{instance_id}\n{problem_statement}"


def _load_train_split() -> list[dict[str, Any]]:
    builder = load_dataset_builder(DATASET_NAME)
    available = list(builder.info.splits.keys())
    if DATASET_SPLIT in available:
        dataset = load_dataset(DATASET_NAME, split=DATASET_SPLIT)
        rows = list(dataset)
    else:
        log.warning(
            "contamination.train_split_missing",
            dataset=DATASET_NAME,
            requested=DATASET_SPLIT,
            available=available,
            fallback="dev+test",
        )
        dev = load_dataset(DATASET_NAME, split="dev")
        test = load_dataset(DATASET_NAME, split="test")
        rows = list(concatenate_datasets([dev, test]))
    return rows


@app.command()
def main(
    output: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--output",
        help="Path for NPZ file (key: embeddings)",
    ),
    batch_size: int = typer.Option(64, "--batch-size"),
) -> None:
    started = time.perf_counter()
    log.info("contamination.load_dataset", dataset=DATASET_NAME, split=DATASET_SPLIT)
    rows = _load_train_split()

    texts = [
        _embedding_text(str(row["instance_id"]), str(row["problem_statement"])) for row in rows
    ]
    n = len(texts)
    log.info("contamination.embed_start", n_instances=n, model=MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=False,
        show_progress_bar=True,
    )
    arr = np.asarray(embeddings, dtype=np.float32)
    if arr.shape != (n, EMBEDDING_DIM):
        msg = f"Unexpected embedding shape {arr.shape!r}, expected ({n}, {EMBEDDING_DIM})"
        raise ValueError(msg)

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, embeddings=arr)

    elapsed_s = time.perf_counter() - started
    size_bytes = output.stat().st_size
    log.info(
        "contamination.saved",
        path=str(output),
        n_embeddings=n,
        model=MODEL_NAME,
        elapsed_s=round(elapsed_s, 2),
        file_size_bytes=size_bytes,
        file_size_mb=round(size_bytes / (1024 * 1024), 2),
    )
    typer.echo(
        f"Wrote {n} embeddings ({MODEL_NAME}) to {output} "
        f"({size_bytes} bytes, {elapsed_s:.1f}s)",
    )


if __name__ == "__main__":
    app()
