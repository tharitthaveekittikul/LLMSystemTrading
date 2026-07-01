"""LLM Analytics API — model performance tied to trade outcomes."""
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.confidence import confidence_bucket
from db.models import LLMCall, PipelineRun, PipelineStep, Trade
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Response schemas ──────────────────────────────────────────────────────────

class ModelPerformanceRow(BaseModel):
    model: str
    provider: str
    runs_participated: int
    trades_triggered: int       # runs where final_action in buy/sell
    profitable_trades: int
    win_rate: float             # profitable_trades / trades_triggered
    avg_profit_usd: float       # avg profit on triggered trades
    total_pnl_usd: float        # sum of all attributed trade profits
    total_cost_usd: float
    avg_cost_usd: float         # per LLM call
    profit_per_dollar: float    # total_pnl / total_cost — key ROI metric
    avg_latency_ms: float
    action_dist: dict[str, float]   # {buy: 0.3, sell: 0.2, hold: 0.4, skip: 0.1}


class LLMAnalyticsSummary(BaseModel):
    best_win_rate_model: str
    best_win_rate: float
    best_roi_model: str
    best_roi: float
    fastest_model: str
    fastest_ms: float
    total_cost_usd: float
    total_trades_triggered: int
    period_days: int


class HeatmapResponse(BaseModel):
    models: list[str]
    symbols: list[str]
    values: list[list[float | None]]    # [model_idx][symbol_idx] = win_rate or None


class TimelinePoint(BaseModel):
    date: str
    by_model: dict[str, float]


class PipelineCombinationRow(BaseModel):
    analysis_model: str
    execution_model: str
    pipeline_key: str           # "gemini-2.5-flash → claude-sonnet-4-6"
    total_runs: int
    trades_triggered: int
    profitable_trades: int
    win_rate: float
    total_pnl_usd: float
    avg_profit_usd: float
    analysis_cost_usd: float
    execution_cost_usd: float
    total_cost_usd: float
    profit_per_dollar: float


# ── Core query ────────────────────────────────────────────────────────────────

async def _fetch_rows(db: AsyncSession, since: datetime) -> list:
    """Join LLMCall → PipelineStep → PipelineRun → Trade for the given period."""
    stmt = (
        select(
            LLMCall.model,
            LLMCall.provider,
            LLMCall.cost_usd,
            LLMCall.duration_ms,
            LLMCall.created_at,
            PipelineStep.run_id,
            PipelineRun.symbol,
            PipelineRun.final_action,
            PipelineRun.task_type,
            Trade.profit,
        )
        .join(PipelineStep, LLMCall.pipeline_step_id == PipelineStep.id)
        .join(PipelineRun, PipelineStep.run_id == PipelineRun.id)
        .outerjoin(Trade, PipelineRun.trade_id == Trade.id)
        .where(LLMCall.created_at >= since)
        .where(PipelineRun.task_type == "signal")
        .where(LLMCall.pipeline_step_id.is_not(None))
    )
    return (await db.execute(stmt)).all()


async def _fetch_pipeline_rows(db: AsyncSession, since: datetime) -> list:
    """Join LLMCall → PipelineStep → PipelineRun → Trade, selecting role for pipeline pivot."""
    stmt = (
        select(
            LLMCall.model,
            LLMCall.role,
            LLMCall.cost_usd,
            PipelineStep.run_id,
            PipelineRun.symbol,
            PipelineRun.final_action,
            Trade.profit,
        )
        .join(PipelineStep, LLMCall.pipeline_step_id == PipelineStep.id)
        .join(PipelineRun, PipelineStep.run_id == PipelineRun.id)
        .outerjoin(Trade, PipelineRun.trade_id == Trade.id)
        .where(LLMCall.created_at >= since)
        .where(PipelineRun.task_type == "signal")
        .where(LLMCall.pipeline_step_id.is_not(None))
    )
    return (await db.execute(stmt)).all()


def _aggregate_pipeline_combinations(rows: list) -> list[PipelineCombinationRow]:
    """
    Group by (analysis_model, execution_model) pair at pipeline_run level.
    Win rate reflects the full pipeline outcome, not individual model contribution.
    """
    run_data: dict[str, dict] = {}

    for row in rows:
        run_id = str(row.run_id)
        if run_id not in run_data:
            run_data[run_id] = {
                "analysis_model": None,
                "execution_model": None,
                "analysis_cost": 0.0,
                "execution_cost": 0.0,
                "action": (row.final_action or "").lower(),
                "profit": float(row.profit) if row.profit is not None else None,
            }
        rd = run_data[run_id]
        role = (row.role or "").lower()
        cost = float(row.cost_usd or 0)
        if role == "execution_decision":
            rd["execution_model"] = row.model
            rd["execution_cost"] += cost
        elif role in ("market_analysis", "chart_vision", "news_analysis"):
            rd["analysis_model"] = row.model
            rd["analysis_cost"] += cost
        else:
            rd["analysis_cost"] += cost  # untagged calls counted as analysis cost

    combos: dict[tuple, list] = defaultdict(list)
    for rd in run_data.values():
        key = (rd["analysis_model"] or "unknown", rd["execution_model"] or "unknown")
        combos[key].append(rd)

    result: list[PipelineCombinationRow] = []
    for (analysis_model, execution_model), runs in combos.items():
        total_runs = len(runs)
        triggered = [r for r in runs if r["action"] in ("buy", "sell")]
        trades_triggered = len(triggered)
        profitable = [r for r in triggered if r["profit"] is not None and r["profit"] > 0]
        profitable_trades = len(profitable)
        win_rate = profitable_trades / trades_triggered if trades_triggered else 0.0

        profits = [r["profit"] for r in triggered if r["profit"] is not None]
        total_pnl = sum(profits)
        avg_profit = sum(profits) / len(profits) if profits else 0.0

        analysis_cost = sum(r["analysis_cost"] for r in runs)
        execution_cost = sum(r["execution_cost"] for r in runs)
        total_cost = analysis_cost + execution_cost
        profit_per_dollar = total_pnl / total_cost if total_cost > 0 else 0.0

        result.append(PipelineCombinationRow(
            analysis_model=analysis_model,
            execution_model=execution_model,
            pipeline_key=f"{analysis_model} → {execution_model}",
            total_runs=total_runs,
            trades_triggered=trades_triggered,
            profitable_trades=profitable_trades,
            win_rate=round(win_rate, 4),
            total_pnl_usd=round(total_pnl, 6),
            avg_profit_usd=round(avg_profit, 6),
            analysis_cost_usd=round(analysis_cost, 8),
            execution_cost_usd=round(execution_cost, 8),
            total_cost_usd=round(total_cost, 8),
            profit_per_dollar=round(profit_per_dollar, 4),
        ))

    return sorted(result, key=lambda r: -r.total_pnl_usd)


def _aggregate_model_performance(rows: list) -> list[ModelPerformanceRow]:
    """
    Aggregate per model. Deduplicates multiple LLM calls within the same run
    so each run is counted only once per model for win/loss attribution.
    """
    # Per-model stats across all calls (cost, latency — one row per LLM call)
    call_stats: dict[str, dict] = {}
    # Per-model, per-run dedup bucket (for win/loss — one entry per unique run)
    run_buckets: dict[str, dict[str, dict]] = defaultdict(dict)

    for row in rows:
        model = row.model
        run_id = str(row.run_id)
        action = (row.final_action or "").lower()

        # Accumulate call-level stats
        if model not in call_stats:
            call_stats[model] = {
                "provider": row.provider,
                "call_count": 0,
                "total_cost": 0.0,
                "total_latency": 0.0,
                "latency_count": 0,
            }
        s = call_stats[model]
        s["call_count"] += 1
        s["total_cost"] += float(row.cost_usd or 0)
        if row.duration_ms is not None:
            s["total_latency"] += row.duration_ms
            s["latency_count"] += 1

        # Dedup run-level stats (first row wins for this run+model combo)
        if run_id not in run_buckets[model]:
            run_buckets[model][run_id] = {
                "symbol": row.symbol,
                "action": action,
                "profit": float(row.profit) if row.profit is not None else None,
            }

    result: list[ModelPerformanceRow] = []
    for model, cs in call_stats.items():
        runs = list(run_buckets[model].values())
        runs_participated = len(runs)

        triggered = [r for r in runs if r["action"] in ("buy", "sell")]
        trades_triggered = len(triggered)

        profitable = [r for r in triggered if r["profit"] is not None and r["profit"] > 0]
        profitable_trades = len(profitable)
        win_rate = profitable_trades / trades_triggered if trades_triggered else 0.0

        profits = [r["profit"] for r in triggered if r["profit"] is not None]
        total_pnl = sum(profits)
        avg_profit = sum(profits) / len(profits) if profits else 0.0

        total_cost = cs["total_cost"]
        avg_cost = total_cost / cs["call_count"] if cs["call_count"] else 0.0
        profit_per_dollar = total_pnl / total_cost if total_cost > 0 else 0.0

        avg_latency = (
            cs["total_latency"] / cs["latency_count"] if cs["latency_count"] else 0.0
        )

        # Action distribution across all runs this model participated in
        action_counts: dict[str, int] = defaultdict(int)
        for r in runs:
            a = r["action"] if r["action"] in ("buy", "sell", "hold", "skip") else "skip"
            action_counts[a] += 1
        action_dist = {
            k: round(v / runs_participated, 4) if runs_participated else 0.0
            for k, v in action_counts.items()
        }

        result.append(ModelPerformanceRow(
            model=model,
            provider=cs["provider"],
            runs_participated=runs_participated,
            trades_triggered=trades_triggered,
            profitable_trades=profitable_trades,
            win_rate=round(win_rate, 4),
            avg_profit_usd=round(avg_profit, 6),
            total_pnl_usd=round(total_pnl, 6),
            total_cost_usd=round(total_cost, 8),
            avg_cost_usd=round(avg_cost, 8),
            profit_per_dollar=round(profit_per_dollar, 4),
            avg_latency_ms=round(avg_latency, 1),
            action_dist=action_dist,
        ))

    return sorted(result, key=lambda r: -r.total_pnl_usd)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/model-performance", response_model=list[ModelPerformanceRow])
async def get_model_performance(
    days: int = Query(30, ge=1, le=365),
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[ModelPerformanceRow]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await _fetch_rows(db, since)
    if account_id is not None:
        rows = [r for r in rows if r.account_id == account_id] if hasattr(rows[0] if rows else object(), "account_id") else rows
    return _aggregate_model_performance(rows)


@router.get("/summary", response_model=LLMAnalyticsSummary)
async def get_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> LLMAnalyticsSummary:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await _fetch_rows(db, since)
    perf = _aggregate_model_performance(rows)

    if not perf:
        return LLMAnalyticsSummary(
            best_win_rate_model="—", best_win_rate=0.0,
            best_roi_model="—", best_roi=0.0,
            fastest_model="—", fastest_ms=0.0,
            total_cost_usd=0.0, total_trades_triggered=0, period_days=days,
        )

    with_trades = [p for p in perf if p.trades_triggered > 0]
    best_wr = max(with_trades, key=lambda p: p.win_rate) if with_trades else perf[0]
    best_roi = max(perf, key=lambda p: p.profit_per_dollar)
    fastest = min((p for p in perf if p.avg_latency_ms > 0), key=lambda p: p.avg_latency_ms, default=perf[0])

    return LLMAnalyticsSummary(
        best_win_rate_model=best_wr.model,
        best_win_rate=best_wr.win_rate,
        best_roi_model=best_roi.model,
        best_roi=best_roi.profit_per_dollar,
        fastest_model=fastest.model,
        fastest_ms=fastest.avg_latency_ms,
        total_cost_usd=round(sum(p.total_cost_usd for p in perf), 8),
        total_trades_triggered=sum(p.trades_triggered for p in perf),
        period_days=days,
    )


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> HeatmapResponse:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await _fetch_rows(db, since)

    # Collect unique (model, run_id) → (symbol, action, profit)
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = (row.model, row.run_id)
        if key not in seen:
            seen[key] = {
                "symbol": row.symbol,
                "action": (row.final_action or "").lower(),
                "profit": float(row.profit) if row.profit is not None else None,
            }

    # Build model×symbol win_rate cells
    # cell_data[model][symbol] = [list of profits for triggered trades]
    cell_data: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for (model, _), data in seen.items():
        if data["action"] in ("buy", "sell"):
            cell_data[model][data["symbol"]].append(data["profit"])

    models = sorted(cell_data.keys())
    symbols_set: set[str] = set()
    for sym_dict in cell_data.values():
        symbols_set.update(sym_dict.keys())
    symbols = sorted(symbols_set)

    values: list[list[float | None]] = []
    for model in models:
        row_vals: list[float | None] = []
        for symbol in symbols:
            trades = cell_data[model].get(symbol, [])
            if not trades:
                row_vals.append(None)
            else:
                wins = sum(1 for p in trades if p is not None and p > 0)
                row_vals.append(round(wins / len(trades), 4))
        values.append(row_vals)

    return HeatmapResponse(models=models, symbols=symbols, values=values)


@router.get("/pnl-timeline", response_model=list[TimelinePoint])
async def get_pnl_timeline(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[TimelinePoint]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await _fetch_rows(db, since)

    # Dedup: unique (model, run_id) → pick daily profit contribution
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = (row.model, row.run_id)
        if key not in seen:
            seen[key] = {
                "model": row.model,
                "date": row.created_at.strftime("%Y-%m-%d"),
                "profit": float(row.profit) if row.profit is not None else 0.0,
                "action": (row.final_action or "").lower(),
            }

    # Group by date → model → sum of profits
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for data in seen.values():
        if data["action"] in ("buy", "sell"):
            buckets[data["date"]][data["model"]] += data["profit"]

    return [
        TimelinePoint(date=date, by_model=dict(by_model))
        for date, by_model in sorted(buckets.items())
    ]


@router.get("/pipelines", response_model=list[PipelineCombinationRow])
async def get_pipeline_combinations(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[PipelineCombinationRow]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await _fetch_pipeline_rows(db, since)
    return _aggregate_pipeline_combinations(rows)


@router.get("/cost-trend", response_model=list[TimelinePoint])
async def get_cost_trend(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[TimelinePoint]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (await db.execute(
        select(LLMCall.model, LLMCall.cost_usd, LLMCall.created_at)
        .where(LLMCall.created_at >= since)
    )).all()

    buckets: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        date = row.created_at.strftime("%Y-%m-%d")
        buckets[date][row.model] += float(row.cost_usd or 0)

    return [
        TimelinePoint(
            date=date,
            by_model={m: round(v, 8) for m, v in by_model.items()},
        )
        for date, by_model in sorted(buckets.items())
    ]


# ── Learning Tab ──────────────────────────────────────────────────────────────

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
    from db.models import AIJournal
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
