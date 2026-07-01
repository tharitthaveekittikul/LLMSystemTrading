"""Research-loop learning views: confidence calibration, signal reliability, lessons."""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.confidence import confidence_bucket
from db.models import AIJournal, Trade
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfidenceBucket(BaseModel):
    bucket: str
    label: str
    win_rate: float
    trade_count: int
    overconfident: bool


class SignalReliabilityRow(BaseModel):
    signal: str
    reliable_pct: float
    sample_count: int
    is_reliable: bool


class LearningLesson(BaseModel):
    lesson: str
    symbol: str
    direction: str
    profit: float
    closed_at: str


class ResearchConfigResponse(BaseModel):
    lessons: list[str]
    blocked_symbols: list[str]
    signal_weights: dict[str, float]
    suggested_params: dict
    last_run_at: str | None
    stats_snapshot: dict


_CONFIDENCE_BUCKET_LABELS = {
    "very_high": "≥80%",
    "high": "65-80%",
    "medium": "50-65%",
    "low": "<50%",
}


def _conf_bucket(c: float) -> tuple[str, str]:
    key = confidence_bucket(c)
    return key, _CONFIDENCE_BUCKET_LABELS[key]


@router.get("/learning/confidence-calibration", response_model=list[ConfidenceBucket])
async def get_confidence_calibration(
    account_id: int | None = Query(None),
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[ConfidenceBucket]:
    """Actual win rate per LLM confidence bucket."""
    since = datetime.now(UTC) - timedelta(days=days)

    q = (
        select(AIJournal.confidence, Trade.profit)
        .join(Trade, AIJournal.trade_id == Trade.id)
        .where(Trade.closed_at.is_not(None), Trade.closed_at >= since, AIJournal.confidence.is_not(None))
    )
    if account_id:
        q = q.where(Trade.account_id == account_id)

    rows = (await db.execute(q)).all()
    buckets: dict[str, dict] = {
        "very_high": {"label": "≥80%", "wins": 0, "total": 0},
        "high":      {"label": "65-80%", "wins": 0, "total": 0},
        "medium":    {"label": "50-65%", "wins": 0, "total": 0},
        "low":       {"label": "<50%", "wins": 0, "total": 0},
    }
    for conf, profit in rows:
        key, _ = _conf_bucket(float(conf))
        buckets[key]["total"] += 1
        if (profit or 0) > 0:
            buckets[key]["wins"] += 1

    result = []
    for key, d in buckets.items():
        if d["total"] == 0:
            continue
        wr = d["wins"] / d["total"]
        result.append(ConfidenceBucket(
            bucket=key, label=d["label"],
            win_rate=round(wr, 3), trade_count=d["total"],
            overconfident=(key == "very_high" and wr < 0.50),
        ))
    return result


@router.get("/learning/signal-reliability", response_model=list[SignalReliabilityRow])
async def get_signal_reliability(
    account_id: int | None = Query(None),
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[SignalReliabilityRow]:
    """Reliability of each indicator signal from post-trade analysis."""
    import json as _json
    since = datetime.now(UTC) - timedelta(days=days)

    q = select(Trade.trade_analysis).where(
        Trade.closed_at.is_not(None), Trade.closed_at >= since, Trade.trade_analysis.is_not(None),
    )
    if account_id:
        q = q.where(Trade.account_id == account_id)

    rows = (await db.execute(q)).scalars().all()
    counts: dict[str, dict[str, int]] = {}
    for ta_json in rows:
        try:
            ta = _json.loads(ta_json)
            for s in ta.get("correct_signals", []):
                counts.setdefault(s, {"correct": 0, "wrong": 0})["correct"] += 1
            for s in ta.get("wrong_signals", []):
                counts.setdefault(s, {"correct": 0, "wrong": 0})["wrong"] += 1
        except Exception:
            continue

    return [
        SignalReliabilityRow(
            signal=sig,
            reliable_pct=round(c["correct"] / max(c["correct"] + c["wrong"], 1) * 100, 1),
            sample_count=c["correct"] + c["wrong"],
            is_reliable=(c["correct"] / max(c["correct"] + c["wrong"], 1)) >= 0.55,
        )
        for sig, c in sorted(counts.items(), key=lambda x: x[1]["correct"] / max(sum(x[1].values()), 1), reverse=True)
    ]


@router.get("/learning/lessons", response_model=list[LearningLesson])
async def get_recent_lessons(
    account_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[LearningLesson]:
    """Lessons extracted from recent losing trades."""
    import json as _json
    q = (
        select(Trade)
        .where(Trade.closed_at.is_not(None), Trade.profit < 0, Trade.trade_analysis.is_not(None))
        .order_by(Trade.closed_at.desc())
        .limit(limit * 3)
    )
    if account_id:
        q = q.where(Trade.account_id == account_id)

    trades = (await db.execute(q)).scalars().all()
    result = []
    for t in trades:
        try:
            ta = _json.loads(t.trade_analysis)
            lesson = ta.get("lesson", "").strip()
            if not lesson:
                continue
            result.append(LearningLesson(
                lesson=lesson, symbol=t.symbol, direction=t.direction,
                profit=round(t.profit or 0, 2),
                closed_at=t.closed_at.isoformat() if t.closed_at else "",
            ))
        except Exception:
            continue
        if len(result) >= limit:
            break
    return result


@router.get("/learning/research-config", response_model=ResearchConfigResponse)
async def get_research_config() -> ResearchConfigResponse:
    """Return current research_config.json from the research loop."""
    from services.research_loop import read_config
    cfg = read_config()
    return ResearchConfigResponse(
        lessons=cfg.get("lessons", []),
        blocked_symbols=cfg.get("blocked_symbols", []),
        signal_weights=cfg.get("signal_reliability", {}),
        suggested_params=cfg.get("suggested_params", {}),
        last_run_at=cfg.get("last_run_at"),
        stats_snapshot=cfg.get("stats_snapshot", {}),
    )
