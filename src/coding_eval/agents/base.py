from __future__ import annotations

from abc import ABC, abstractmethod

from coding_eval.dataset.schema import Task


class AgentAdapter(ABC):
    agent_id: str

    @abstractmethod
    async def solve(self, task: Task, repo_path: str) -> tuple[str, float]:
        """Return (unified_diff_patch, cost_usd). Patch may be empty on failure."""

    @abstractmethod
    def name(self) -> str: ...

