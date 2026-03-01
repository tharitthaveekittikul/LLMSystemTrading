"""Test that get_rates_range raises RuntimeError when MT5 is not installed."""
import asyncio
from unittest.mock import patch

import pytest


def test_get_rates_range_raises_when_mt5_unavailable():
    """When MetaTrader5 package is not installed, get_rates_range raises RuntimeError."""
    from mt5.bridge import MT5Bridge, AccountCredentials

    creds = AccountCredentials(login=1, password="x", server="s")
    bridge = MT5Bridge(creds)

    with patch("mt5.bridge.MT5_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="MetaTrader5 package"):
            asyncio.run(bridge.get_rates_range("EURUSD", 16408, None, None))


def test_get_rates_range_method_exists():
    """MT5Bridge must have a get_rates_range method."""
    from mt5.bridge import MT5Bridge
    assert hasattr(MT5Bridge, "get_rates_range")
    assert callable(MT5Bridge.get_rates_range)
