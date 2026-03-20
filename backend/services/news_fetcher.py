"""ForexFactory economic calendar fetcher.

Fetches the weekly calendar from the unofficial FF JSON mirror, normalises all
timestamps to UTC, and upserts rows into the economic_events table.

Schedule: daily at 23:00 UTC (06:00 Bangkok) via scheduler.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FETCH_TIMEOUT = 10.0  # seconds

# Maps FF `country` (currency code) → trading symbols affected by that currency's news.
# XAUUSD is under USD: gold is priced in USD and reacts strongly to USD events.
CURRENCY_SYMBOL_MAP: dict[str, list[str]] = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD"],
    "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD"],
    "GBP": ["GBPUSD", "GBPJPY", "EURGBP", "GBPCHF", "GBPAUD", "GBPCAD"],
    "JPY": ["USDJPY", "GBPJPY", "EURJPY", "AUDJPY", "CADJPY"],
    "AUD": ["AUDUSD", "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD"],
    "CAD": ["USDCAD", "CADJPY", "AUDCAD", "EURCAD", "GBPCAD"],
    "CHF": ["USDCHF", "EURCHF", "GBPCHF", "AUDCHF"],
    "NZD": ["NZDUSD", "NZDJPY", "AUDNZD"],
}


def _make_ff_id(title: str, currency: str, event_utc: datetime) -> str:
    """Stable 16-char dedup key: sha1(title|currency|date|HH:MM)."""
    raw = f"{title}|{currency}|{event_utc.date()}|{event_utc.hour:02d}:{event_utc.minute:02d}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


async def fetch_and_store_events(db: AsyncSession) -> int:
    """Fetch the FF weekly calendar and upsert into economic_events.

    Returns the number of rows inserted or updated.
    Raises on HTTP or parse errors so the caller can log/retry.
    """
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
        resp = await client.get(FF_URL)
        resp.raise_for_status()
        raw_events: list[dict] = resp.json()

    logger.info("FF calendar fetched | events=%d", len(raw_events))

    upserted = 0
    now_utc = datetime.now(UTC)

    for raw in raw_events:
        title = raw.get("title", "").strip()
        currency = raw.get("country", "").strip().upper()
        raw_date = raw.get("date", "")

        if not title or not currency or not raw_date:
            continue

        # Parse Eastern-time offset (e.g. "-04:00") → UTC
        try:
            event_utc = datetime.fromisoformat(raw_date).astimezone(UTC)
        except (ValueError, TypeError):
            logger.warning("FF event skipped — bad date: %r", raw_date)
            continue

        ff_id = _make_ff_id(title, currency, event_utc)
        affected = json.dumps(CURRENCY_SYMBOL_MAP.get(currency, []))
        impact = raw.get("impact", "").strip()
        forecast = raw.get("forecast", "") or None
        previous = raw.get("previous", "") or None

        await db.execute(
            text("""
                INSERT INTO economic_events
                    (ff_id, title, currency, event_utc, impact, forecast, previous,
                     affected_symbols, fetched_at, updated_at)
                VALUES
                    (:ff_id, :title, :currency, :event_utc, :impact, :forecast, :previous,
                     :affected_symbols, :now, :now)
                ON CONFLICT (ff_id) DO UPDATE SET
                    forecast         = EXCLUDED.forecast,
                    previous         = EXCLUDED.previous,
                    impact           = EXCLUDED.impact,
                    affected_symbols = EXCLUDED.affected_symbols,
                    updated_at       = EXCLUDED.updated_at
            """),
            {
                "ff_id": ff_id,
                "title": title,
                "currency": currency,
                "event_utc": event_utc,
                "impact": impact,
                "forecast": forecast,
                "previous": previous,
                "affected_symbols": affected,
                "now": now_utc,
            },
        )
        upserted += 1

    await db.commit()
    logger.info("FF calendar upserted | rows=%d", upserted)
    return upserted
