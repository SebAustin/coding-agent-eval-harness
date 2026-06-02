from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .schema import Task


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            yield json.loads(stripped)


def load_tasks(path: str | Path, *, limit: int = 0) -> list[Task]:
    tasks: list[Task] = []
    for obj in iter_jsonl(path):
        tasks.append(Task.model_validate(obj))
        if limit and len(tasks) >= limit:
            break
    return tasks


def dump_tasks(tasks: Iterable[Task], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(t.model_dump_json())
            f.write("\n")

