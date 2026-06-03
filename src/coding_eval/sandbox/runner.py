from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import docker
from docker.errors import APIError, DockerException
from docker.models.containers import Container
from pydantic import BaseModel, ConfigDict

from coding_eval.sandbox.images import DEFAULT_SANDBOX_IMAGE


class SandboxResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool


@dataclass(frozen=True, slots=True)
class _RunSpec:
    repo_path: str
    patch: str
    test_files: list[str]


class DockerSandbox:
    TIMEOUT_S: int = 120
    MEMORY_LIMIT: str = "512m"
    NANO_CPUS: int = int(1e9)

    def __init__(self, image: str = DEFAULT_SANDBOX_IMAGE) -> None:
        self._image = image
        self._client = docker.from_env()

    @property
    def image(self) -> str:
        return self._image

    async def run_patch(
        self,
        repo_path: str,
        patch: str,
        test_files: list[str],
    ) -> SandboxResult:
        """Apply patch in an isolated container and run pytest. Network disabled."""
        spec = _RunSpec(repo_path=repo_path, patch=patch, test_files=test_files)
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._run_patch_sync, spec),
                timeout=self.TIMEOUT_S,
            )
        except TimeoutError:
            return SandboxResult(
                exit_code=124,
                stdout="",
                stderr="sandbox timed out",
                duration_ms=float(self.TIMEOUT_S * 1000),
                timed_out=True,
            )

    def _run_patch_sync(self, spec: _RunSpec) -> SandboxResult:
        start = time.perf_counter()
        tmpdir = tempfile.mkdtemp(prefix="coding-eval-sandbox-")
        try:
            shutil.copytree(
                spec.repo_path,
                tmpdir,
                dirs_exist_ok=True,
                symlinks=True,
            )
            patch_path = Path(tmpdir) / "agent.patch"
            patch_text = spec.patch if spec.patch.endswith("\n") else f"{spec.patch}\n"
            patch_path.write_text(patch_text, encoding="utf-8")

            test_args = " ".join(spec.test_files)
            command = (
                "cd /workspace && "
                "git apply --check agent.patch && "
                "git apply agent.patch && "
                f"PYTHONPATH=/workspace pytest {test_args} -x --timeout=30 -q 2>&1"
            )
            return self._docker_run(
                tmpdir=tmpdir,
                command=command,
                start=start,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _docker_run(
        self,
        *,
        tmpdir: str,
        command: str,
        start: float,
    ) -> SandboxResult:
        exit_code = 1
        stdout = ""
        stderr = ""
        container: Container | None = None
        try:
            container = self._client.containers.create(
                self._image,
                command=["/bin/bash", "-c", command],
                volumes={tmpdir: {"bind": "/workspace", "mode": "rw"}},
                network_mode="none",
                mem_limit=self.MEMORY_LIMIT,
                nano_cpus=self.NANO_CPUS,
                working_dir="/workspace",
            )
            container.start()
            wait_result = container.wait(timeout=self.TIMEOUT_S)
            exit_code = int(wait_result.get("StatusCode", 1))
            stdout = _decode_output(container.logs(stdout=True, stderr=True))
        except APIError as exc:
            stderr = str(exc)
            if container is not None:
                try:
                    stdout = _decode_output(container.logs(stdout=True, stderr=True))
                except DockerException:
                    stdout = _decode_output(getattr(exc, "stderr", None))
        except DockerException as exc:
            stderr = str(exc)
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

        duration_ms = (time.perf_counter() - start) * 1000.0
        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=False,
        )


def _decode_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)
