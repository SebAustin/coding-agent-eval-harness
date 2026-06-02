from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from coding_eval.patching.git_apply import PatchApplyError, apply_unified_diff


def test_git_apply_good_diff(tmp_path: Path, fixtures_dir: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(str(repo_dir))
    (repo_dir / ".gitignore").write_text("", encoding="utf-8")
    repo.index.add([".gitignore"])
    repo.index.commit("init")

    diff = (fixtures_dir / "good.diff").read_text(encoding="utf-8")
    apply_unified_diff(str(repo_dir), diff)
    assert (repo_dir / "hello.txt").exists()


def test_git_apply_raises_on_bad_diff(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    Repo.init(str(repo_dir))
    with pytest.raises(PatchApplyError):
        apply_unified_diff(str(repo_dir), "not a diff")

