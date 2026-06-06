from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentSolveResult:
    patch: str
    cost_usd: float
    raw_response: str = ""


__all__ = ["AgentSolveResult"]
