from __future__ import annotations

from abc import ABC, abstractmethod

from coding_eval.agents.result import AgentSolveResult
from coding_eval.dataset.schema import Task


class AgentAdapter(ABC):
    agent_id: str

    @abstractmethod
    async def solve(self, task: Task, repo_path: str) -> AgentSolveResult:
        """Return patch, cost, and optional raw model output for debugging."""

    @abstractmethod
    def name(self) -> str: ...

