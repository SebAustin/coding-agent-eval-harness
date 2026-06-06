from __future__ import annotations

import tempfile
from pathlib import Path

from git import GitCommandError, Repo


class PatchApplyError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def apply_unified_diff(repo_path: str, patch: str) -> None:
    ok, message = check_unified_diff(repo_path, patch)
    if not ok:
        raise PatchApplyError(message)
    repo_dir = Path(repo_path)
    repo = Repo(str(repo_dir))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".patch",
        delete=False,
    ) as tmp:
        tmp.write(patch if patch.endswith("\n") else f"{patch}\n")
        patch_path = tmp.name

    try:
        repo.git.apply("--whitespace=nowarn", patch_path)
    except GitCommandError as e:
        raise PatchApplyError(str(e)) from e
    finally:
        Path(patch_path).unlink(missing_ok=True)


def check_unified_diff(repo_path: str, patch: str) -> tuple[bool, str]:
    repo_dir = Path(repo_path)
    if not repo_dir.exists():
        return False, f"repo_path does not exist: {repo_path}"
    if not patch.strip():
        return False, "empty patch"

    repo = Repo(str(repo_dir))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".patch",
        delete=False,
    ) as tmp:
        tmp.write(patch if patch.endswith("\n") else f"{patch}\n")
        patch_path = tmp.name

    try:
        repo.git.apply("--check", "--whitespace=nowarn", patch_path)
    except GitCommandError as e:
        return False, str(e)
    finally:
        Path(patch_path).unlink(missing_ok=True)
    return True, ""


__all__ = ["PatchApplyError", "apply_unified_diff", "check_unified_diff"]
