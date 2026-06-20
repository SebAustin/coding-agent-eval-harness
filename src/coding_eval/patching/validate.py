from __future__ import annotations

import py_compile
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from coding_eval.patching.git_apply import PatchApplyError, apply_unified_diff
from coding_eval.rubric._patch_files import changed_py_files

# Unified-diff source/target header lines, capturing the path with the conventional
# a/ or b/ prefix stripped. Git always writes those prefixes, so a real top-level dir
# named "a"/"b" still arrives prefixed (e.g. `+++ b/a/foo.py`).
_DIFF_HEADER_RE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(.+)$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _diff_target_paths(patch: str) -> list[str]:
    """Extract the file paths named in a unified diff's ``---``/``+++`` headers."""
    paths: list[str] = []
    for line in patch.splitlines():
        match = _DIFF_HEADER_RE.match(line)
        if match is None:
            continue
        # Drop a trailing tab-delimited timestamp some diff tools append.
        path = match.group(1).split("\t", 1)[0].strip()
        if path:
            paths.append(path)
    return paths


def _escapes_repo_root(repo_root: Path, raw_path: str) -> bool:
    # Diffs may use either slash style; normalize so Windows-style paths are caught too.
    normalized = raw_path.replace("\\", "/")
    if PurePosixPath(normalized).is_absolute() or _WINDOWS_DRIVE_RE.match(normalized):
        return True
    # Resolve against the repo root (collapsing any `..`) and require containment.
    resolved = (repo_root / normalized).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return True
    return False


def patch_paths_within_repo(repo_path: str, patch: str) -> tuple[bool, str]:
    """Reject a patch whose diff target paths escape the cloned repo root.

    Defense-in-depth (SECURITY.md M-2): ``git apply`` already refuses ``..`` and
    absolute-path traversal at both the ``--check`` and apply stages, but this guard
    removes the harness's sole reliance on git's behavior. It parses the ``---``/``+++``
    headers, normalizes each path, and fails if any is absolute (POSIX or Windows-drive)
    or resolves outside ``repo_path``. ``/dev/null`` (new/deleted file sentinel) is
    ignored. Returns the same ``(ok, error)`` shape as the other validators so the
    solver's retry/format-fixup loop handles a rejection uniformly.
    """
    repo_root = Path(repo_path).resolve()
    for raw_path in _diff_target_paths(patch):
        if raw_path == "/dev/null":
            continue
        if _escapes_repo_root(repo_root, raw_path):
            return False, f"patch target path escapes repo root: {raw_path!r}"
    return True, ""


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


__all__ = ["patch_paths_within_repo", "patch_py_files_compile"]
