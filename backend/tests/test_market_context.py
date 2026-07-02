from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.market_context import (
    _extract_currencies,
    fetch_high_impact_events,
    fetch_upcoming_events,
    format_news_context,
)


def _mock_calendar(events: list[dict]):
    """Context manager patching the ForexFactory HTTP call to return `events`."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = events
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    return patch("services.market_context.httpx.AsyncClient", return_value=mock_client)


def test_extract_currencies_forex():
    result = _extract_currencies(["EURUSD", "GBPJPY"])
    assert "EUR" in result
    assert "USD" in result
    assert "GBP" in result
    assert "JPY" in result


def test_extract_currencies_short_symbol():
    # symbols shorter than 6 chars should not crash
    result = _extract_currencies(["XAU"])
    assert isinstance(result, set)


def test_format_news_context_empty():
    assert format_news_context([]) == ""


def test_format_news_context_formats_events():
    events = [
        {
            "time": "2026-02-28T14:00:00+00:00",
            "currency": "USD",
            "title": "Non-Farm Payrolls",
            "impact": "High",
            "forecast": "200K",
            "previous": "180K",
        }
    ]
    result = format_news_context(events)
    assert "Non-Farm Payrolls" in result
    assert "USD" in result
    assert "High" in result
    assert "200K" in result


@pytest.mark.asyncio
async def test_fetch_upcoming_events_returns_empty_on_error():
    """Network failure returns empty list, never raises."""
    with patch("services.market_context.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.side_effect = Exception("network error")
        mock_cls.return_value = mock_client

        result = await fetch_upcoming_events(["EURUSD"])
    assert result == []


@pytest.mark.asyncio
async def test_fetch_upcoming_events_filters_by_currency():
    """Only events for currencies matching the given symbols are returned."""
    from datetime import UTC, datetime, timedelta

    future_time = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": future_time, "country": "EUR", "title": "CPI", "impact": "High", "forecast": "", "previous": ""},
        {"date": future_time, "country": "JPY", "title": "BOJ Rate", "impact": "High", "forecast": "", "previous": ""},
    ]

    with patch("services.market_context.httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_events
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        result = await fetch_upcoming_events(["EURUSD"])

    # Only EUR and USD currencies should match — JPY should be filtered out
    currencies = {e["currency"] for e in result}
    assert "EUR" in currencies
    assert "JPY" not in currencies


@pytest.mark.asyncio
async def test_fetch_upcoming_events_excludes_past_event_by_default():
    """hours_back defaults to 0 — a recently-fired event stays excluded."""
    past_time = (datetime.now(UTC) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": past_time, "country": "USD", "title": "NFP", "impact": "High", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_upcoming_events(["EURUSD"])
    assert result == []


@pytest.mark.asyncio
async def test_fetch_upcoming_events_includes_recent_past_event_with_hours_back():
    """A recently-fired event is included when hours_back covers it."""
    past_time = (datetime.now(UTC) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": past_time, "country": "USD", "title": "NFP", "impact": "High", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_upcoming_events(["EURUSD"], hours_back=1.0)
    assert len(result) == 1
    assert result[0]["title"] == "NFP"


@pytest.mark.asyncio
async def test_fetch_upcoming_events_hours_back_does_not_include_older_events():
    """An event further back than hours_back is still excluded."""
    old_time = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": old_time, "country": "USD", "title": "NFP", "impact": "High", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_upcoming_events(["EURUSD"], hours_back=1.0)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_high_impact_events_default_includes_medium():
    """Default impact_levels (settings.news_impact_levels) includes Medium."""
    soon = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": soon, "country": "USD", "title": "Fed Speaker", "impact": "Medium", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_high_impact_events(["EURUSD"])
    assert len(result) == 1
    assert result[0]["title"] == "Fed Speaker"


@pytest.mark.asyncio
async def test_fetch_high_impact_events_custom_impact_levels_excludes_medium():
    """Passing impact_levels=["High"] excludes Medium-impact events."""
    soon = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": soon, "country": "USD", "title": "Fed Speaker", "impact": "Medium", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_high_impact_events(["EURUSD"], impact_levels=["High"])
    assert result == []


@pytest.mark.asyncio
async def test_fetch_high_impact_events_lookback_window_catches_recent_event():
    """A recently-fired High-impact event is caught by the lookback window."""
    just_fired = (datetime.now(UTC) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": just_fired, "country": "USD", "title": "NFP", "impact": "High", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_high_impact_events(["EURUSD"], lookback_minutes=60, lookahead_minutes=60)
    assert len(result) == 1
    assert result[0]["title"] == "NFP"


@pytest.mark.asyncio
async def test_fetch_high_impact_events_zero_lookback_excludes_past_event():
    """lookback_minutes=0 preserves forward-only behavior."""
    just_fired = (datetime.now(UTC) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    mock_events = [
        {"date": just_fired, "country": "USD", "title": "NFP", "impact": "High", "forecast": "", "previous": ""},
    ]
    with _mock_calendar(mock_events):
        result = await fetch_high_impact_events(["EURUSD"], lookback_minutes=0, lookahead_minutes=60)
    assert result == []
