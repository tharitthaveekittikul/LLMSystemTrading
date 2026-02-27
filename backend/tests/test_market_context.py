from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.market_context import (
    _extract_currencies,
    fetch_upcoming_events,
    format_news_context,
)


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
        {"date": future_time, "currency": "EUR", "title": "CPI", "impact": "High", "forecast": "", "previous": ""},
        {"date": future_time, "currency": "JPY", "title": "BOJ Rate", "impact": "High", "forecast": "", "previous": ""},
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
