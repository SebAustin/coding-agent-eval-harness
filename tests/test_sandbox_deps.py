from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coding_eval.sandbox.deps import (
    WHEELS_DIR,
    has_offline_wheels,
    offline_install_shell,
    prepare_offline_wheels,
    wheel_cache_root,
)


def test_install_specs_from_pyproject(tmp_path: Path) -> None:
    from coding_eval.sandbox.deps import _install_specs

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    specs = _install_specs(tmp_path)
    assert ["."] in specs
    assert [".[dev]"] in specs


def test_has_offline_wheels_false_when_missing(tmp_path: Path) -> None:
    assert has_offline_wheels(tmp_path) is False


def test_has_offline_wheels_true_when_populated(tmp_path: Path) -> None:
    wheels = tmp_path / WHEELS_DIR
    wheels.mkdir()
    (wheels / "attrs-23.2.0-py3-none-any.whl").touch()
    assert has_offline_wheels(tmp_path) is True


def test_offline_install_shell_includes_no_index() -> None:
    cmd = offline_install_shell()
    assert "--no-index" in cmd
    assert "for w in .eval_wheels" in cmd


def test_poetry_runtime_packages(tmp_path: Path) -> None:
    from coding_eval.sandbox.deps import _poetry_packages

    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\npython = \">=3.8\"\nclick = \"^8.0\"\n",
        encoding="utf-8",
    )
    pkgs = _poetry_packages(tmp_path, section="runtime")
    assert "click" in pkgs


def test_poetry_dev_packages(tmp_path: Path) -> None:
    from coding_eval.sandbox.deps import _poetry_packages

    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dev-dependencies]\nattrs = \"^21.0\"\n",
        encoding="utf-8",
    )
    assert "attrs" in _poetry_packages(tmp_path, section="dev")


@patch("coding_eval.sandbox.deps.subprocess.run")
def test_download_wheels_uses_uv(mock_run: MagicMock, tmp_path: Path) -> None:
    from coding_eval.sandbox.deps import _download_wheels

    mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    assert _download_wheels(tmp_path, wheels, ["."]) is True
    cmd = mock_run.call_args[0][0]
    assert cmd[:4] == ["uv", "run", "--with", "pip"]


@patch("coding_eval.sandbox.deps.subprocess.run")
def test_prepare_offline_wheels_uses_cache(
    mock_run: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "wheel-cache"
    monkeypatch.setenv("CODING_EVAL_WHEEL_CACHE", str(cache_root))
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    cache_dir = wheel_cache_root() / "Textualize_rich" / "abc123456789" / "v3"
    cache_dir.mkdir(parents=True)
    (cache_dir / "attrs.whl").touch()

    assert prepare_offline_wheels(tmp_path, repo_id="Textualize/rich", commit="abc123456789") is True
    assert (tmp_path / WHEELS_DIR / "attrs.whl").is_file()
    mock_run.assert_not_called()


@patch("coding_eval.sandbox.deps.subprocess.run")
def test_prepare_offline_wheels_downloads_on_cache_miss(
    mock_run: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "wheel-cache"
    monkeypatch.setenv("CODING_EVAL_WHEEL_CACHE", str(cache_root))
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    def _download(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        cache_dir = wheel_cache_root() / "Textualize_rich" / "abc123456789" / "v3"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "click.whl").touch()
        return subprocess.CompletedProcess([], 0, "", "")

    mock_run.side_effect = _download

    assert prepare_offline_wheels(tmp_path, repo_id="Textualize/rich", commit="abc123456789") is True
    assert (tmp_path / WHEELS_DIR / "click.whl").is_file()
    mock_run.assert_called()


@patch("coding_eval.sandbox.deps.subprocess.run")
def test_prepare_offline_wheels_returns_false_when_all_specs_fail(
    mock_run: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODING_EVAL_WHEEL_CACHE", str(tmp_path / "wheel-cache"))
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    mock_run.return_value = subprocess.CompletedProcess([], 1, "", "network error")

    assert prepare_offline_wheels(tmp_path, repo_id="Textualize/rich", commit="abc123456789") is False
    assert not has_offline_wheels(tmp_path)
