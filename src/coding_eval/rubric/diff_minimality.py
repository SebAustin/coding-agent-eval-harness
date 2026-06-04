from __future__ import annotations

MAX_REASONABLE_LINES = 200


def _count_changed_lines(patch: str) -> int:
    count = 0
    for line in patch.splitlines():
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count


def score(patch: str) -> float:
    changed = _count_changed_lines(patch)
    ratio = min(changed / MAX_REASONABLE_LINES, 1.0)
    return 1.0 - ratio


__all__ = ["MAX_REASONABLE_LINES", "score"]
