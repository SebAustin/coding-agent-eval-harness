from __future__ import annotations

import shutil
from pathlib import Path

import docker
import pytest
from git import Repo

from coding_eval.sandbox.images import DEFAULT_SANDBOX_IMAGE
from coding_eval.sandbox.runner import DockerSandbox


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except docker.errors.DockerException:
        return False


def _image_available(image: str) -> bool:
    try:
        client = docker.from_env()
        client.images.get(image)
        return True
    except docker.errors.DockerException:
        return False


@pytest.fixture
def cloned_sample_repo(tmp_path: Path, fixtures_dir: Path) -> Path:
    repo_dir = tmp_path / "repo"
    shutil.copytree(fixtures_dir / "sample_repo", repo_dir)
    repo = Repo.init(str(repo_dir))
    repo.index.add(["greeter.py", "tests/test_greeter.py"])
    repo.index.commit("init")
    return repo_dir


@pytest.fixture
def sample_patch(cloned_sample_repo: Path) -> str:
    """Unified diff from committed tree to fixed greeter (matches test expectation)."""
    greeter_path = cloned_sample_repo / "greeter.py"
    original = greeter_path.read_text(encoding="utf-8")
    greeter_path.write_text(
        "def greet() -> str:\n    return \"new\"\n",
        encoding="utf-8",
    )
    repo = Repo(str(cloned_sample_repo))
    patch = repo.git.diff("HEAD")
    greeter_path.write_text(original, encoding="utf-8")
    return patch


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_run_patch_applies_and_passes(
    cloned_sample_repo: Path,
    sample_patch: str,
) -> None:
    if not _docker_available():
        pytest.skip("Docker daemon not available")
    if not _image_available(DEFAULT_SANDBOX_IMAGE):
        pytest.skip(f"Sandbox image {DEFAULT_SANDBOX_IMAGE!r} not built")

    sandbox = DockerSandbox(image=DEFAULT_SANDBOX_IMAGE)
    result = await sandbox.run_patch(
        str(cloned_sample_repo),
        sample_patch,
        ["tests/test_greeter.py"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "passed" in result.stdout
