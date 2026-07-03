"""Tests for MT5Bridge.get_broker_symbol caching and warning-suppression.

Root cause under test: mt5.symbols_get() only reliably lists symbols that have
been through symbol_select() at least once this terminal session, so a bare
name (or an already-suffixed one, e.g. 'XAUUSD.s') can appear "missing" even
though it's genuinely tradable — copy_rates_from_pos() succeeds moments later
because get_rates() calls symbol_select() itself. get_broker_symbol() now
selects the name first (so a real symbol IS enumerated) and only warns when
the symbol is still unconfirmed after that. Results are cached per session in
the module-level _SYMBOL_CACHE, cleared on disconnect().
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

import mt5.bridge as bridge_module
from mt5.bridge import AccountCredentials, MT5Bridge


def _make_creds() -> AccountCredentials:
    return AccountCredentials(login=12345, password="pw", server="srv")


def _symbol(name: str) -> MagicMock:
    s = MagicMock()
    s.name = name
    s.visible = True
    return s


@pytest.fixture(autouse=True)
def _clear_symbol_cache():
    bridge_module._SYMBOL_CACHE.clear()
    yield
    bridge_module._SYMBOL_CACHE.clear()


@pytest.mark.asyncio
async def test_valid_symbol_confirmed_via_symbol_select_does_not_warn(caplog):
    """A real broker symbol not yet enumerated by symbols_get() should not warn."""
    bridge = MT5Bridge(_make_creds())

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.symbol_select.return_value = True  # symbol IS selectable
        mock_mt5.symbols_get.return_value = []       # but not yet enumerated

        with caplog.at_level(logging.DEBUG, logger="mt5.bridge"):
            result = await bridge.get_broker_symbol("XAUUSD.s")

    assert result == "XAUUSD.s"
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)
    assert any("confirmed via symbol_select" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_unresolvable_symbol_still_warns(caplog):
    """A genuinely unknown symbol (select fails, no enumeration match) still warns."""
    bridge = MT5Bridge(_make_creds())

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.symbol_select.return_value = False
        mock_mt5.symbols_get.return_value = [_symbol("EURUSD.s")]

        with caplog.at_level(logging.WARNING, logger="mt5.bridge"):
            result = await bridge.get_broker_symbol("NOPE")

    assert result == "NOPE"
    assert any("No broker match found" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_get_broker_symbol_caches_and_skips_second_lookup():
    bridge = MT5Bridge(_make_creds())

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.symbol_select.return_value = True
        mock_mt5.symbols_get.return_value = [_symbol("EURUSD.s")]

        first = await bridge.get_broker_symbol("EURUSD")
        second = await bridge.get_broker_symbol("EURUSD")

    assert first == second == "EURUSD.s"
    # Only the first call should have hit MT5 — the second is served from cache.
    assert mock_mt5.symbols_get.call_count == 1
    assert mock_mt5.symbol_select.call_count == 1


@pytest.mark.asyncio
async def test_disconnect_clears_symbol_cache():
    bridge = MT5Bridge(_make_creds())

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.symbol_select.return_value = True
        mock_mt5.symbols_get.return_value = [_symbol("EURUSD.s")]
        await bridge.get_broker_symbol("EURUSD")
        assert bridge_module._SYMBOL_CACHE == {"EURUSD": "EURUSD.s"}

        await bridge.disconnect()
        assert bridge_module._SYMBOL_CACHE == {}
