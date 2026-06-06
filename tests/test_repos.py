from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from git.exc import GitCommandError

from coding_eval.dataset.repos import RepoCloneError, clone_repo_at_commit


def test_clone_repo_at_commit_success(tmp_path: Path) -> None:
    dest = tmp_path / "repo"
    mock_repo = MagicMock()
    commit = "abc1234567890abcdef1234567890abcdef1234"
    with patch("coding_eval.dataset.repos.Repo.clone_from", return_value=mock_repo):
        path = clone_repo_at_commit("owner/repo", commit, dest)
    assert path == dest
    mock_repo.git.fetch.assert_called()
    mock_repo.git.checkout.assert_called_with(commit)


def test_clone_repo_rejects_placeholder_commit(tmp_path: Path) -> None:
    with pytest.raises(RepoCloneError, match="placeholder"):
        clone_repo_at_commit("owner/repo", "a1b2c3d", tmp_path / "repo")


def test_clone_repo_at_commit_failure(tmp_path: Path) -> None:
    dest = tmp_path / "repo"
    with (
        patch(
            "coding_eval.dataset.repos.Repo.clone_from",
            side_effect=GitCommandError("clone", "failed"),
        ),
        pytest.raises(RepoCloneError),
    ):
        clone_repo_at_commit("owner/repo", "bad", dest)
    assert not dest.exists()
