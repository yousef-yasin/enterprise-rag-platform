"""Evaluation read + trigger endpoints (docs/ARCHITECTURE.md §33.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AdminDep, PrincipalDep, SessionDep, SettingsDep
from app.core.errors import NotFoundError
from app.infra.db.models import EvalRun, EvalSample
from app.schemas.common import Page
from app.schemas.eval import EvalRunResponse, EvalSampleResponse

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/runs", response_model=Page[EvalRunResponse])
async def list_runs(
    session: SessionDep,
    _principal: PrincipalDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    dataset: str | None = Query(default=None),
) -> Page[EvalRunResponse]:
    stmt = select(EvalRun).order_by(EvalRun.created_at.desc())
    if dataset:
        stmt = stmt.where(EvalRun.dataset_name == dataset)
    rows = list((await session.execute(stmt.limit(limit + 1).offset(offset))).scalars())
    has_more = len(rows) > limit
    return Page(
        items=[EvalRunResponse.from_model(r) for r in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
async def get_run(
    run_id: uuid.UUID, session: SessionDep, _principal: PrincipalDep
) -> EvalRunResponse:
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise NotFoundError("eval run not found")
    return EvalRunResponse.from_model(run)


@router.get("/runs/{run_id}/samples", response_model=Page[EvalSampleResponse])
async def list_samples(
    run_id: uuid.UUID,
    session: SessionDep,
    _principal: PrincipalDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Page[EvalSampleResponse]:
    stmt = (
        select(EvalSample)
        .where(EvalSample.run_id == run_id)
        .order_by(EvalSample.id)
        .limit(limit + 1)
        .offset(offset)
    )
    rows = list((await session.execute(stmt)).scalars())
    has_more = len(rows) > limit
    return Page(
        items=[EvalSampleResponse.from_model(s) for s in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


class EvalRunRequest(BaseModel):
    knowledge_base_id: uuid.UUID
    dataset: str
    split: str = "smoke"
    label: str | None = None
    judge: bool = True
    limit: int | None = None


@router.post("/runs", response_model=EvalRunResponse, status_code=201)
async def trigger_run(
    body: EvalRunRequest,
    settings: SettingsDep,
    session: SessionDep,
    _admin: AdminDep,
) -> EvalRunResponse:
    """Synchronous run — admin only. Long datasets should use the CLI / nightly job."""
    from app.services.evaluation import EvaluationService

    run_id = await EvaluationService(settings).run(
        knowledge_base_id=body.knowledge_base_id,
        dataset=body.dataset,
        split=body.split,
        config_label=body.label,
        judge_enabled=body.judge,
        limit=body.limit,
    )
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise NotFoundError("eval run vanished after creation")
    return EvalRunResponse.from_model(run)
