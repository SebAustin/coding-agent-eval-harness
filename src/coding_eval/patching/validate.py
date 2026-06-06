from __future__ import annotations

import py_compile
import shutil
import tempfile
from pathlib import Path

from coding_eval.patching.git_apply import PatchApplyError, apply_unified_diff
from coding_eval.rubric._patch_files import changed_py_files


def patch_py_files_compile(repo_path: str, patch: str) -> tuple[bool, str]:
    """Apply patch in a temp copy and py_compile each touched .py file."""
    py_files = [path for path in changed_py_files(patch) if path.endswith(".py")]
    if not py_files:
        return True, ""

    tmpdir = tempfile.mkdtemp(prefix="coding-eval-compile-")
    try:
        shutil.copytree(repo_path, tmpdir, dirs_exist_ok=True, symlinks=True)
        apply_unified_diff(tmpdir, patch)
        root = Path(tmpdir)
        for rel in py_files:
            path = root / rel
            if not path.is_file():
                continue
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                return False, str(exc)
    except PatchApplyError as exc:
        return False, exc.message
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return True, ""


__all__ = ["patch_py_files_compile"]
