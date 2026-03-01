"""Pipeline run log API — list and detail views for AI trading pipeline runs."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PipelineRun, PipelineStep
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class PipelineStepOut(BaseModel):
    id: int
    run_id: int
    seq: int
    step_name: str
    status: str
    input_json: str | None
    output_json: str | None
    error: str | None
    duration_ms: int

    model_config = {"from_attributes": True}


class PipelineRunSummary(BaseModel):
    id: int
    account_id: int
    symbol: str
    timeframe: str
    status: str
    final_action: str | None
    total_duration_ms: int | None
    journal_id: int | None
    trade_id: int | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_custom(cls, run: PipelineRun) -> "PipelineRunSummary":
        return cls(
            id=run.id,
            account_id=run.account_id,
            symbol=run.symbol,
            timeframe=run.timeframe,
            status=run.status,
            final_action=run.final_action,
            total_duration_ms=run.total_duration_ms,
            journal_id=run.journal_id,
            trade_id=run.trade_id,
            created_at=run.created_at.isoformat(),
        )


class PipelineRunDetail(BaseModel):
    run: PipelineRunSummary
    steps: list[PipelineStepOut]


@router.get("/runs", response_model=list[PipelineRunSummary])
async def list_runs(
    account_id: int | None = Query(None),
    symbol: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[PipelineRunSummary]:
    q = select(PipelineRun).order_by(desc(PipelineRun.created_at))
    if account_id is not None:
        q = q.where(PipelineRun.account_id == account_id)
    if symbol:
        q = q.where(PipelineRun.symbol == symbol.upper())
    if status:
        q = q.where(PipelineRun.status == status)
    q = q.limit(limit).offset(offset)
    runs = (await db.execute(q)).scalars().all()
    return [PipelineRunSummary.from_orm_custom(r) for r in runs]


@router.get("/runs/{run_id}", response_model=PipelineRunDetail)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> PipelineRunDetail:
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    steps_q = (
        select(PipelineStep)
        .where(PipelineStep.run_id == run_id)
        .order_by(PipelineStep.seq)
    )
    steps = (await db.execute(steps_q)).scalars().all()
    return PipelineRunDetail(
        run=PipelineRunSummary.from_orm_custom(run),
        steps=[PipelineStepOut.model_validate(s) for s in steps],
    )
