from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from radon.complexity import cc_visit

from coding_eval.patching.git_apply import PatchApplyError, apply_unified_diff
from coding_eval.rubric._patch_files import changed_py_files


def _mean_complexity(repo_root: Path, relative_paths: list[str]) -> float:
    scores: list[float] = []
    for rel in relative_paths:
        path = repo_root / rel
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        blocks = cc_visit(source)
        if not blocks:
            scores.append(0.0)
            continue
        scores.append(sum(block.complexity for block in blocks) / len(blocks))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def score(patch: str, repo_path: str) -> float:
    py_files = changed_py_files(patch)
    if not py_files:
        return 1.0

    tmpdir = tempfile.mkdtemp(prefix="coding-eval-complexity-")
    try:
        root = Path(tmpdir)
        shutil.copytree(repo_path, root, dirs_exist_ok=True, symlinks=True)
        before = _mean_complexity(root, py_files)
        try:
            apply_unified_diff(str(root), patch)
        except PatchApplyError:
            return 0.0
        after = _mean_complexity(root, py_files)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    delta = after - before
    if delta <= 0:
        return 1.0
    return max(0.0, 1.0 - delta / 10.0)


__all__ = ["score"]
