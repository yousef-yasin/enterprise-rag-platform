"""Evaluation DTOs (docs/ARCHITECTURE.md §33.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.infra.db.models import EvalRun, EvalSample


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    dataset: str
    split: str
    status: str
    git_sha: str | None
    config_label: str | None
    judge_model: str | None
    n_samples: int
    metrics: dict[str, Any]
    config_snapshot: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_model(cls, run: EvalRun) -> EvalRunResponse:
        n = run.metrics.get("n_samples") if isinstance(run.metrics, dict) else None
        return cls(
            id=run.id,
            dataset=run.dataset_name,
            split=run.dataset_split,
            status="completed",
            git_sha=run.git_sha,
            config_label=run.name,
            judge_model=run.judge_model,
            n_samples=int(n) if isinstance(n, int | float) else 0,
            metrics=run.metrics or {},
            config_snapshot=run.config_snapshot or {},
            created_at=run.created_at,
            completed_at=run.created_at,
        )


class EvalSampleResponse(BaseModel):
    id: uuid.UUID
    question: str
    expected_answer: str | None
    generated_answer: str | None
    retrieved_chunk_ids: list[str]
    cited_chunk_ids: list[str]
    scores: dict[str, Any]
    cost_usd: float

    @classmethod
    def from_model(cls, s: EvalSample) -> EvalSampleResponse:
        return cls(
            id=s.id,
            question=s.question,
            expected_answer=s.expected_answer,
            generated_answer=s.generated_answer,
            retrieved_chunk_ids=list(s.retrieved_chunk_ids),
            cited_chunk_ids=list(s.cited_chunk_ids),
            scores=s.scores or {},
            cost_usd=float(s.cost_usd),
        )
