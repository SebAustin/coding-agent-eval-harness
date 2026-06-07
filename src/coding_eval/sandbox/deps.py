from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

WHEELS_DIR = ".eval_wheels"
# Bumped to v4: caches now also hold manylinux wheels (see _download_linux_wheels).
_CACHE_VERSION = "v4"
_PACKAGE_EXTRAS = (".", ".[dev]", ".[tests]", ".[test]", ".[all]")

# Wheels are downloaded on the host but installed in the Linux sandbox. Pure-python
# packages ship universal (py3-none-any) wheels that work anywhere, but compiled
# packages (numpy, pydantic-core, ...) download as host-specific wheels the
# container can't use. So additionally fetch manylinux cp312 wheels for the
# resolved deps; the host wheels/sdists stay alongside as a fallback.
_LINUX_WHEEL_ARGS = [
    "--only-binary=:all:",
    "--python-version",
    "3.12",
    "--implementation",
    "cp",
    "--abi",
    "cp312",
    "--platform",
    "manylinux2014_x86_64",
    "--platform",
    "manylinux_2_28_x86_64",
]


def wheel_cache_root() -> Path:
    raw = os.environ.get("CODING_EVAL_WHEEL_CACHE", "~/.cache/coding-eval/wheels")
    return Path(raw).expanduser()


def _wheel_cache_dir(repo_id: str, commit: str) -> Path:
    safe_repo = repo_id.replace("/", "_")
    return wheel_cache_root() / safe_repo / commit[:12] / _CACHE_VERSION


def _poetry_packages(repo_path: Path, *, section: str) -> list[str]:
    pyproject = repo_path / "pyproject.toml"
    if not pyproject.exists():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return []
    poetry = data.get("tool", {}).get("poetry", {})
    if section == "dev":
        deps = poetry.get("dev-dependencies", {})
        if not deps:
            group_dev = poetry.get("group", {}).get("dev", {})
            deps = group_dev.get("dependencies", {})
    else:
        deps = poetry.get("dependencies", {})
    return [str(name) for name in deps if str(name).lower() != "python"]


def _install_specs(repo_path: Path) -> list[list[str]]:
    specs: list[list[str]] = []
    if (repo_path / "pyproject.toml").exists() or (repo_path / "setup.py").exists():
        specs.extend([[extra] for extra in _PACKAGE_EXTRAS])
    if (repo_path / "requirements.txt").exists():
        specs.append(["-r", "requirements.txt"])
    if (repo_path / "requirements-dev.txt").exists():
        specs.append(["-r", "requirements-dev.txt"])
    return specs


def _download_wheels(
    repo_path: Path,
    dest: Path,
    spec: list[str],
    *,
    target_linux: bool = False,
) -> bool:
    cmd = [
        "uv",
        "run",
        "--with",
        "pip",
        "python",
        "-m",
        "pip",
        "download",
        "--dest",
        str(dest),
        *(_LINUX_WHEEL_ARGS if target_linux else []),
        *spec,
    ]
    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        log.debug(
            "sandbox.wheels_download_failed",
            spec=spec,
            stderr=result.stderr[-500:],
        )
        return False
    return True


def _name_version(filename: str) -> tuple[str, str] | None:
    """Parse (name, version) from a wheel or sdist filename, else None."""
    if filename.endswith(".whl"):
        parts = filename[: -len(".whl")].split("-")
        if len(parts) >= 2:  # noqa: PLR2004 - name-version-...
            return parts[0], parts[1]
    for suffix in (".tar.gz", ".zip"):
        if filename.endswith(suffix):
            stem = filename[: -len(suffix)]
            if "-" in stem:
                name, version = stem.rsplit("-", 1)
                return name, version
    return None


def _pinned_specs_from_dir(dest: Path) -> list[str]:
    """``name==version`` for every distribution already downloaded into ``dest``."""
    specs: dict[str, str] = {}
    for path in dest.iterdir():
        parsed = _name_version(path.name)
        if parsed is not None:
            name, version = parsed
            specs.setdefault(name.lower(), f"{name}=={version}")
    return sorted(specs.values())


def _download_linux_wheels(repo_path: Path, dest: Path) -> None:
    """Fetch manylinux cp312 wheels for the resolved deps, alongside host wheels.

    Best-effort: a single batch call, falling back to per-package so one
    distribution without a manylinux wheel doesn't drop the rest.
    """
    specs = _pinned_specs_from_dir(dest)
    if not specs:
        return
    if _download_wheels(repo_path, dest, specs, target_linux=True):
        return
    for spec in specs:
        _download_wheels(repo_path, dest, [spec], target_linux=True)


def _download_poetry_packages(repo_path: Path, dest: Path) -> None:
    for package in _poetry_packages(repo_path, section="runtime"):
        _download_wheels(repo_path, dest, [package])
    for package in _poetry_packages(repo_path, section="dev"):
        _download_wheels(repo_path, dest, [package])


def has_offline_wheels(repo_path: str | Path) -> bool:
    wheels_dir = Path(repo_path) / WHEELS_DIR
    return wheels_dir.is_dir() and any(wheels_dir.iterdir())


def offline_install_shell() -> str:
    """Shell fragment: install all cached wheels; project code comes from /workspace."""
    return (
        "for w in .eval_wheels/*.whl .eval_wheels/*.tar.gz; do "
        '[ -f "$w" ] && pip install -q --no-index --find-links=.eval_wheels "$w" || true; '
        "done"
    )


def prepare_offline_wheels(
    repo_path: Path,
    *,
    repo_id: str,
    commit: str,
) -> bool:
    """Download wheels on the host and copy them into repo/.eval_wheels for sandbox use."""
    wheels_dir = repo_path / WHEELS_DIR
    if wheels_dir.exists():
        shutil.rmtree(wheels_dir)

    cache_dir = _wheel_cache_dir(repo_id, commit)
    if cache_dir.is_dir() and any(cache_dir.iterdir()):
        shutil.copytree(cache_dir, wheels_dir)
        log.info(
            "sandbox.wheels_cached",
            repo=repo_id,
            commit=commit[:12],
            n_files=len(list(wheels_dir.iterdir())),
        )
        return True

    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        for spec in _install_specs(repo_path):
            _download_wheels(repo_path, cache_dir, spec)
        _download_poetry_packages(repo_path, cache_dir)
        _download_linux_wheels(repo_path, cache_dir)
        if any(cache_dir.iterdir()):
            shutil.copytree(cache_dir, wheels_dir)
            log.info(
                "sandbox.wheels_downloaded",
                repo=repo_id,
                commit=commit[:12],
                n_files=len(list(wheels_dir.iterdir())),
            )
            return True
    finally:
        if cache_dir.is_dir() and not any(cache_dir.iterdir()):
            shutil.rmtree(cache_dir, ignore_errors=True)

    if wheels_dir.exists():
        shutil.rmtree(wheels_dir, ignore_errors=True)
    log.warning("sandbox.wheels_unavailable", repo=repo_id, commit=commit[:12])
    return False


__all__ = [
    "WHEELS_DIR",
    "has_offline_wheels",
    "offline_install_shell",
    "prepare_offline_wheels",
    "wheel_cache_root",
]
