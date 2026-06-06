from __future__ import annotations

import re
import subprocess

from coding_eval.agents.base import AgentAdapter
from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task
from coding_eval.patching.extract import extract_unified_patch

_DIFF_START_RE = re.compile(r"^---\s", re.MULTILINE)
_AIDER_TIMEOUT_S = 60


class AiderAdapter(AgentAdapter):
    agent_id = "aider"

    def name(self) -> str:
        return self.agent_id

    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        _ = task.issue_title
        completed = subprocess.run(  # noqa: S603
            [
                "aider",
                "--no-git",
                "--yes",
                "--message",
                task.issue_body,
                "--show-diff",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=_AIDER_TIMEOUT_S,
            check=False,
        )
        combined = f"{completed.stdout}\n{completed.stderr}"
        patch = extract_unified_patch(combined) or _extract_diff(combined)
        return AgentSolveResult(patch=patch, cost_usd=0.0, raw_response=combined)


def _extract_diff(output: str) -> str:
    match = _DIFF_START_RE.search(output)
    if match is None:
        return ""
    return output[match.start() :].strip()


__all__ = ["AiderAdapter"]
