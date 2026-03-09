import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from core.currency import get_usd_thb_rate, _rate_cache

@pytest.mark.asyncio
async def test_get_usd_thb_rate_success():
    # Reset cache
    _rate_cache["usd_thb"] = 36.0
    _rate_cache["last_updated"] = datetime.min.replace(tzinfo=UTC)
    
    mock_response = {
        "result": "success",
        "rates": {"THB": 35.5}
    }
    
    with patch("core.currency.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        
        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.json = MagicMock(return_value=mock_response)
        mock_get_res.raise_for_status = MagicMock()
        
        mock_client.get = AsyncMock(return_value=mock_get_res)
        
        rate = await get_usd_thb_rate()
        
        assert rate == 35.5
        assert _rate_cache["usd_thb"] == 35.5
        assert (datetime.now(UTC) - _rate_cache["last_updated"]) < timedelta(seconds=1)

@pytest.mark.asyncio
async def test_get_usd_thb_rate_cache_hit():
    # Setup cache
    _rate_cache["usd_thb"] = 34.0
    _rate_cache["last_updated"] = datetime.now(UTC)
    
    with patch("core.currency.httpx.AsyncClient") as mock_client_class:
        rate = await get_usd_thb_rate()
        
        # Should not call API
        mock_client_class.assert_not_called()
        assert rate == 34.0

@pytest.mark.asyncio
async def test_get_usd_thb_rate_failure_fallback():
    # Reset cache to a known value
    _rate_cache["usd_thb"] = 36.0
    _rate_cache["last_updated"] = datetime.min.replace(tzinfo=UTC)
    
    with patch("core.currency.httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=Exception("API Down"))
        
        rate = await get_usd_thb_rate()
        
        # Should return fallback (the current cached value)
        assert rate == 36.0
        # Should have updated last_updated
        assert (datetime.now(UTC) - _rate_cache["last_updated"]) > timedelta(hours=5)
