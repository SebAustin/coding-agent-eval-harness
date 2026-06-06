from __future__ import annotations

import shutil
from pathlib import Path

from git import Repo
from git.exc import GitCommandError


class RepoCloneError(Exception):
    """Failed to clone or checkout a repository at the requested commit."""


def clone_repo_at_commit(owner_repo: str, commit: str, dest: Path) -> Path:
    if len(commit) < 12:
        msg = (
            f"base_commit {commit!r} looks like a placeholder; "
            f"rebuild tasks with coding-eval build-dataset or use data/tasks/built_15.jsonl"
        )
        raise RepoCloneError(msg)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{owner_repo}.git"
    try:
        repo = Repo.clone_from(url, dest, no_checkout=True, multi_options=["--filter=blob:none"])
        try:
            repo.git.fetch("--depth", "1", "origin", commit)
        except GitCommandError:
            repo.git.fetch("origin", commit)
        repo.git.checkout(commit)
    except GitCommandError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        msg = f"failed to clone {owner_repo} at {commit}: {exc}"
        raise RepoCloneError(msg) from exc
    return dest


__all__ = ["RepoCloneError", "clone_repo_at_commit"]
