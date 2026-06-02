from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException
from pydantic import BaseModel, ConfigDict, Field


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
    CPU_QUOTA: float = 1.0

    def __init__(self, image: str = "coding-eval-sandbox:latest") -> None:
        self._image = image
        self._client = docker.from_env()

    async def run_patch(
        self,
        repo_path: str,
        patch: str,
        test_files: list[str],
    ) -> SandboxResult:
        """Apply patch in an isolated container and run pytest. Network disabled."""
        spec = _RunSpec(repo_path=repo_path, patch=patch, test_files=test_files)
        return await asyncio.to_thread(self._run_patch_sync, spec)

    def _run_patch_sync(self, spec: _RunSpec) -> SandboxResult:
        start = time.perf_counter()
        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = 1

        repo_abs = str(Path(spec.repo_path).resolve())
        env: dict[str, str] = {}

        # Note: we intentionally do not implement patch application or test selection fully yet.
        # This skeleton only establishes the isolation boundary and container constraints.
        try:
            container = self._client.containers.run(
                self._image,
                command=None,
                detach=True,
                network_mode="none",
                mem_limit=self.MEMORY_LIMIT,
                nano_cpus=int(self.CPU_QUOTA * 1_000_000_000),
                read_only=True,
                tmpfs={"/tmp": "size=64m"},
                volumes={repo_abs: {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                environment=env,
            )
        except DockerException as e:  # pragma: no cover
            dur_ms = (time.perf_counter() - start) * 1000.0
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration_ms=dur_ms,
                timed_out=False,
            )

        try:
            try:
                res: dict[str, Any] = container.wait(timeout=self.TIMEOUT_S)
                exit_code = int(res.get("StatusCode", 1))
            except Exception:  # pragma: no cover
                timed_out = True
                exit_code = 124
                try:
                    container.kill()
                finally:
                    pass

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
        finally:
            try:
                container.remove(force=True)
            except Exception:  # pragma: no cover
                pass

        dur_ms = (time.perf_counter() - start) * 1000.0
        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=dur_ms,
            timed_out=timed_out,
        )

