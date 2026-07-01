"""Market context — ForexFactory public economic calendar.

Fetches the current week's calendar from the community JSON feed (no auth required).
Falls back to an empty list on any network or parse error — never raises.

Usage:
    events = await fetch_upcoming_events(["EURUSD", "GBPJPY"])
    context_str = format_news_context(events)  # pass to analyze_market()
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_REQUEST_TIMEOUT = 10.0


async def fetch_upcoming_events(
    symbols: list[str], hours_ahead: float = 24, hours_back: float = 0
) -> list[dict[str, Any]]:
    """Return High/Medium-impact events for currencies in `symbols`, within
    [now - hours_back, now + hours_ahead].

    Returns [] on any error — never raises.
    """
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_FF_CALENDAR_URL)
            resp.raise_for_status()
            events: list[dict] = resp.json()
    except Exception as exc:
        logger.warning("ForexFactory calendar fetch failed: %s", exc)
        return []

    now = datetime.now(UTC)
    cutoff = now + timedelta(hours=hours_ahead)
    window_start = now - timedelta(hours=hours_back)
    currencies = _extract_currencies(symbols)

    filtered = []
    for event in events:
        if event.get("impact") not in ("High", "Medium"):
            continue
        if event.get("currency") not in currencies:
            continue
        try:
            event_dt = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if event_dt <= window_start or event_dt > cutoff:
            continue
        filtered.append(
            {
                "time": event_dt.isoformat(),
                "currency": event["currency"],
                "title": event.get("title", ""),
                "impact": event.get("impact", ""),
                "forecast": event.get("forecast", ""),
                "previous": event.get("previous", ""),
            }
        )
    return filtered


async def fetch_high_impact_events(
    symbols: list[str],
    lookahead_minutes: int | None = None,
    lookback_minutes: int | None = None,
    impact_levels: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return events within the news gate window for symbol currencies —
    upcoming events (anticipation risk) and recently-fired events (post-
    release volatility risk). Defaults come from settings.news_lookahead_minutes
    / news_lookback_minutes / news_impact_levels.

    Used by the news filter gate — never raises.
    """
    lookahead = lookahead_minutes if lookahead_minutes is not None else settings.news_lookahead_minutes
    lookback = lookback_minutes if lookback_minutes is not None else settings.news_lookback_minutes
    levels = set(impact_levels if impact_levels is not None else settings.news_impact_levels)

    events = await fetch_upcoming_events(
        symbols, hours_ahead=lookahead / 60.0, hours_back=lookback / 60.0
    )
    return [e for e in events if e["impact"] in levels]


def format_news_context(events: list[dict[str, Any]]) -> str:
    """Format events list into a string suitable for the LLM prompt."""
    if not events:
        return ""
    lines = ["Upcoming Economic Events (next 24h):"]
    for e in events:
        line = f"  - {e['time']} | {e['currency']} | {e['impact']} | {e['title']}"
        if e.get("forecast"):
            line += f" | Forecast: {e['forecast']}"
        if e.get("previous"):
            line += f" | Previous: {e['previous']}"
        lines.append(line)
    return "\n".join(lines)


def _extract_currencies(symbols: list[str]) -> set[str]:
    """Extract 3-letter currency codes from forex symbols (e.g. EURUSD → EUR, USD)."""
    currencies: set[str] = set()
    for sym in symbols:
        sym = sym.upper()
        if len(sym) >= 6:
            currencies.add(sym[:3])
            currencies.add(sym[3:6])
    return currencies
