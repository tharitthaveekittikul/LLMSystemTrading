"""Economic calendar API routes."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EconomicEvent
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class EconomicEventResponse(BaseModel):
    id: int
    title: str
    currency: str
    event_utc: datetime
    impact: str
    forecast: str | None
    previous: str | None
    actual: str | None
    affected_symbols: list[str]
    llm_signal: str | None
    llm_summary: str | None
    llm_provider: str | None
    llm_model: str | None
    llm_analyzed_at: datetime | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None
    llm_total_tokens: int | None
    llm_cost_usd: float | None
    llm_duration_ms: int | None
    llm_raw_response: str | None
    analysis_error: str | None

    model_config = {"from_attributes": True}


class EconomicEventPatch(BaseModel):
    actual: str | None = None


class FetchResult(BaseModel):
    stored: int


class AnalyzeResult(BaseModel):
    analyzed: int


class DebugAnalysisResponse(BaseModel):
    input_prompt: list[dict]
    raw_response: str
    parsed_json: dict | None
    signal: str | None
    summary: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(ev: EconomicEvent) -> EconomicEventResponse:
    try:
        symbols = json.loads(ev.affected_symbols) if ev.affected_symbols else []
    except (ValueError, TypeError):
        symbols = []
    return EconomicEventResponse(
        id=ev.id,
        title=ev.title,
        currency=ev.currency,
        event_utc=ev.event_utc,
        impact=ev.impact,
        forecast=ev.forecast,
        previous=ev.previous,
        actual=ev.actual,
        affected_symbols=symbols,
        llm_signal=ev.llm_signal,
        llm_summary=ev.llm_summary,
        llm_provider=ev.llm_provider,
        llm_model=ev.llm_model,
        llm_analyzed_at=ev.llm_analyzed_at,
        llm_input_tokens=ev.llm_input_tokens,
        llm_output_tokens=ev.llm_output_tokens,
        llm_total_tokens=ev.llm_total_tokens,
        llm_cost_usd=float(ev.llm_cost_usd) if ev.llm_cost_usd is not None else None,
        llm_duration_ms=ev.llm_duration_ms,
        llm_raw_response=ev.llm_raw_response,
        analysis_error=ev.analysis_error,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[EconomicEventResponse])
async def list_events(
    impact: str | None = None,
    currency: str | None = None,
    symbol: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[EconomicEventResponse]:
    """List economic events. Defaults to current week if no date range provided."""
    stmt = select(EconomicEvent)

    if date_from:
        try:
            stmt = stmt.where(EconomicEvent.event_utc >= datetime.fromisoformat(date_from).astimezone(UTC))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date_from format (use ISO 8601)")
    if date_to:
        try:
            stmt = stmt.where(EconomicEvent.event_utc <= datetime.fromisoformat(date_to).astimezone(UTC))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date_to format (use ISO 8601)")
    if not date_from and not date_to:
        # Default: current week (Mon–Sun UTC)
        now = datetime.now(UTC)
        week_start = now - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=7)
        stmt = stmt.where(
            EconomicEvent.event_utc >= week_start.replace(hour=0, minute=0, second=0, microsecond=0),
            EconomicEvent.event_utc < week_end.replace(hour=0, minute=0, second=0, microsecond=0),
        )

    if impact:
        stmt = stmt.where(EconomicEvent.impact == impact)
    if currency:
        stmt = stmt.where(EconomicEvent.currency == currency.upper())

    stmt = stmt.order_by(EconomicEvent.event_utc)
    rows = (await db.execute(stmt)).scalars().all()

    if symbol:
        # Post-filter: check if symbol is in affected_symbols JSON
        rows = [r for r in rows if symbol.upper() in (json.loads(r.affected_symbols or "[]"))]

    return [_to_response(r) for r in rows]


@router.get("/{event_id}", response_model=EconomicEventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)) -> EconomicEventResponse:
    ev = await db.get(EconomicEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    return _to_response(ev)


@router.patch("/{event_id}", response_model=EconomicEventResponse)
async def patch_event(
    event_id: int,
    body: EconomicEventPatch,
    db: AsyncSession = Depends(get_db),
) -> EconomicEventResponse:
    """Update the user-entered actual value for an event."""
    ev = await db.get(EconomicEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    ev.actual = body.actual
    await db.commit()
    await db.refresh(ev)
    logger.info("Economic event actual updated | id=%d actual=%r", event_id, body.actual)
    return _to_response(ev)


@router.post("/fetch", response_model=FetchResult)
async def fetch_events(db: AsyncSession = Depends(get_db)) -> FetchResult:
    """Manually trigger a fetch of the FF weekly calendar."""
    from services.news_fetcher import fetch_and_store_events
    try:
        stored = await fetch_and_store_events(db)
    except Exception as exc:
        logger.error("Manual news fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Fetch failed: {exc}")
    return FetchResult(stored=stored)


@router.post("/{event_id}/analyze", response_model=EconomicEventResponse)
async def analyze_event_endpoint(
    event_id: int,
    db: AsyncSession = Depends(get_db),
) -> EconomicEventResponse:
    """Manually trigger LLM analysis for a single event."""
    ev = await db.get(EconomicEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    from services.news_analyzer import analyze_event
    await analyze_event(ev, db)
    await db.refresh(ev)
    return _to_response(ev)


@router.post("/{event_id}/analyze-debug", response_model=DebugAnalysisResponse)
async def analyze_event_debug(
    event_id: int,
    db: AsyncSession = Depends(get_db),
) -> DebugAnalysisResponse:
    """Re-run LLM analysis and return the raw prompt + response without saving to DB."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from ai.orchestrator import _call_llm_for_role
    from services.news_analyzer import _SYSTEM_PROMPT, _build_human_prompt, _resolve_llm

    ev = await db.get(EconomicEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    llm = await _resolve_llm(db)
    human_text = _build_human_prompt(ev)
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_text)]

    result = await _call_llm_for_role(llm, messages, "news_analysis")

    raw: dict | None = result.content if isinstance(result.content, dict) else None
    if raw is None and result.raw_text:
        import re as _re
        text = _re.sub(r"^```[a-z]*\n?", "", result.raw_text.strip(), flags=_re.IGNORECASE)
        text = _re.sub(r"\n?```$", "", text.strip())
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                raw = parsed
        except Exception:
            pass

    signal = str(raw.get("signal", "HOLD")).upper() if raw else None
    summary = (raw.get("summary") or None) if raw else None

    return DebugAnalysisResponse(
        input_prompt=result.prompt or [],
        raw_response=result.raw_text,
        parsed_json=raw,
        signal=signal,
        summary=summary,
    )


@router.post("/analyze-today", response_model=AnalyzeResult)
async def analyze_today(db: AsyncSession = Depends(get_db)) -> AnalyzeResult:
    """Analyze all HIGH-impact events in the next 24 h that have no LLM signal."""
    from services.news_analyzer import analyze_today_events
    count = await analyze_today_events(db)
    return AnalyzeResult(analyzed=count)
