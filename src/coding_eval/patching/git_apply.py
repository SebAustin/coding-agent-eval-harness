from __future__ import annotations

import tempfile
from pathlib import Path

from git import GitCommandError, Repo


class PatchApplyError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def apply_unified_diff(repo_path: str, patch: str) -> None:
    repo_dir = Path(repo_path)
    if not repo_dir.exists():
        msg = f"repo_path does not exist: {repo_path}"
        raise PatchApplyError(msg)

    repo = Repo(str(repo_dir))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".patch",
        delete=False,
    ) as tmp:
        tmp.write(patch)
        patch_path = tmp.name

    try:
        repo.git.apply("--whitespace=nowarn", patch_path)
    except GitCommandError as e:
        raise PatchApplyError(str(e)) from e
    finally:
        Path(patch_path).unlink(missing_ok=True)
