"""LLM Usage API — token consumption and cost breakdown."""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.currency import get_usd_thb_rate
from core.llm_pricing import get_pricing_list
from db.models import LLMCall
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Response schemas ──────────────────────────────────────────────────────────

class ProviderStats(BaseModel):
    cost_usd: float
    tokens: int
    calls: int


class LLMUsageSummary(BaseModel):
    total_cost_usd: float
    total_tokens: int
    total_calls: int
    active_models: list[str]
    by_provider: dict[str, ProviderStats]
    usd_thb_rate: float


class LLMTimeseriesPoint(BaseModel):
    date: str
    google: float
    anthropic: float
    openai: float
    openrouter: float


class LLMModelUsage(BaseModel):
    model: str
    provider: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float


class LLMPricingEntry(BaseModel):
    model: str
    provider: str
    input_per_1m_usd: float | None
    output_per_1m_usd: float | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _period_start(period: str) -> datetime:
    now = datetime.now(UTC)
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    # month (default)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=LLMUsageSummary)
async def get_summary(
    period: str = Query("month", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
) -> LLMUsageSummary:
    since = _period_start(period)
    rows = (await db.execute(
        select(LLMCall).where(LLMCall.created_at >= since)
    )).scalars().all()

    total_cost = sum(float(r.cost_usd or 0) for r in rows)
    total_tokens = sum(r.total_tokens or 0 for r in rows)
    active_models = sorted({r.model for r in rows})

    by_provider: dict[str, ProviderStats] = {
        "google":      ProviderStats(cost_usd=0.0, tokens=0, calls=0),
        "anthropic":   ProviderStats(cost_usd=0.0, tokens=0, calls=0),
        "openai":      ProviderStats(cost_usd=0.0, tokens=0, calls=0),
        "openrouter":  ProviderStats(cost_usd=0.0, tokens=0, calls=0),
    }
    for r in rows:
        p = r.provider if r.provider in by_provider else "openai"
        by_provider[p].cost_usd += float(r.cost_usd or 0)
        by_provider[p].tokens += r.total_tokens or 0
        by_provider[p].calls += 1

    rate = await get_usd_thb_rate()

    return LLMUsageSummary(
        total_cost_usd=round(total_cost, 8),
        total_tokens=total_tokens,
        total_calls=len(rows),
        active_models=active_models,
        by_provider=by_provider,
        usd_thb_rate=rate,
    )


@router.get("/timeseries", response_model=list[LLMTimeseriesPoint])
async def get_timeseries(
    granularity: str = Query("daily", pattern="^(daily|hourly)$"),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> list[LLMTimeseriesPoint]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (await db.execute(
        select(LLMCall).where(LLMCall.created_at >= since)
    )).scalars().all()

    buckets: dict[str, dict[str, float]] = {}
    for r in rows:
        key = (
            r.created_at.strftime("%Y-%m-%d %H:00")
            if granularity == "hourly"
            else r.created_at.strftime("%Y-%m-%d")
        )
        if key not in buckets:
            buckets[key] = {"google": 0.0, "anthropic": 0.0, "openai": 0.0, "openrouter": 0.0}
        provider = r.provider if r.provider in buckets[key] else "openai"
        buckets[key][provider] += float(r.cost_usd or 0)

    return [
        LLMTimeseriesPoint(
            date=k,
            google=round(v["google"], 8),
            anthropic=round(v["anthropic"], 8),
            openai=round(v["openai"], 8),
            openrouter=round(v["openrouter"], 8),
        )
        for k, v in sorted(buckets.items())
    ]


@router.get("/by-model", response_model=list[LLMModelUsage])
async def get_by_model(
    period: str = Query("month", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
) -> list[LLMModelUsage]:
    since = _period_start(period)
    rows = (await db.execute(
        select(LLMCall).where(LLMCall.created_at >= since)
    )).scalars().all()

    agg: dict[str, dict] = {}
    for r in rows:
        k = r.model
        if k not in agg:
            agg[k] = {
                "model": r.model, "provider": r.provider,
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
                "total_tokens": 0, "cost_usd": 0.0,
            }
        agg[k]["calls"] += 1
        agg[k]["input_tokens"]  += r.input_tokens  or 0
        agg[k]["output_tokens"] += r.output_tokens or 0
        agg[k]["total_tokens"]  += r.total_tokens  or 0
        agg[k]["cost_usd"]      += float(r.cost_usd or 0)

    return [
        LLMModelUsage(**v)
        for v in sorted(agg.values(), key=lambda x: -x["cost_usd"])
    ]


@router.get("/pricing", response_model=list[LLMPricingEntry])
async def get_pricing() -> list[LLMPricingEntry]:
    return [LLMPricingEntry(**p) for p in get_pricing_list()]
