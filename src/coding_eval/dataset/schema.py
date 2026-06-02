from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    task_id: str
    repo: str  # "owner/repo"
    base_commit: str  # SHA the agent starts from
    issue_number: int
    issue_title: str
    issue_body: str
    test_files: list[str]  # relative paths of test files that cover this area
    hints_text: str = ""  # optional hints from issue thread
    source: str = "github"


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    patch: str  # unified diff produced by agent
    test_pass_rate: float  # 0..1
    diff_minimality: float  # 0..1
    complexity_delta: float  # 0..1
    style_score: float  # 0..1
    semantic_score: float  # 0..1
    composite_score: float  # weighted sum
    is_contaminated: bool
    contamination_similarity: float
    latency_ms: float
    cost_usd: float
    error: str | None = None
    run_id: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

