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

logger = logging.getLogger(__name__)

_FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_REQUEST_TIMEOUT = 10.0


async def fetch_upcoming_events(
    symbols: list[str], hours_ahead: int = 24
) -> list[dict[str, Any]]:
    """Return High/Medium-impact events for currencies in `symbols`, within `hours_ahead` hours.

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
        if event_dt <= now or event_dt > cutoff:
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
