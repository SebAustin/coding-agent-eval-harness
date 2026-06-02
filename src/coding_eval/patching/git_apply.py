from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, Repo


@dataclass(frozen=True, slots=True)
class PatchApplyError(RuntimeError):
    message: str

    def __str__(self) -> str:  # noqa: D105
        return self.message


def apply_unified_diff(repo_path: str, patch: str) -> None:
    repo_dir = Path(repo_path)
    if not repo_dir.exists():
        msg = f"repo_path does not exist: {repo_path}"
        raise PatchApplyError(msg)

    repo = Repo(str(repo_dir))
    try:
        repo.git.execute(
            ["git", "apply", "--whitespace=nowarn", "--reject", "--recount", "-"],
            istream=patch.encode("utf-8"),
        )
    except GitCommandError as e:
        raise PatchApplyError(str(e)) from e

