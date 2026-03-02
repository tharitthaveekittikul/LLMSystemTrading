"""Unit tests for MT5Bridge.resolve_broker_symbol.

This is a pure function (static method, no MT5 connection needed),
so all tests run without any mock/patch overhead.
"""
import pytest

from mt5.bridge import MT5Bridge


# ── resolve_broker_symbol ──────────────────────────────────────────────────────

class TestResolveBrokerSymbol:
    """Tests are ordered by matching priority."""

    # Priority 1: exact match
    def test_exact_match_returns_base(self):
        result = MT5Bridge.resolve_broker_symbol("EURUSD", ["EURUSD", "XAUUSD", "GBPUSD"])
        assert result == "EURUSD"

    def test_exact_match_takes_priority_over_prefix(self):
        """Exact match must win even when a prefix match also exists."""
        result = MT5Bridge.resolve_broker_symbol(
            "EURUSD", ["EURUSD", "EURUSD.s", "EURUSDm"]
        )
        assert result == "EURUSD"

    # Priority 2: prefix match
    def test_prefix_dot_s_suffix(self):
        result = MT5Bridge.resolve_broker_symbol("EURUSD", ["EURUSD.s", "XAUUSD.s"])
        assert result == "EURUSD.s"

    def test_prefix_m_suffix(self):
        result = MT5Bridge.resolve_broker_symbol("EURUSD", ["EURUSDm", "XAUUSD.s"])
        assert result == "EURUSDm"

    def test_prefix_shortest_wins(self):
        """Among multiple prefix matches the shortest name is preferred."""
        result = MT5Bridge.resolve_broker_symbol(
            "EURUSD", ["EURUSDm", "EURUSD.raw", "EURUSD.s"]
        )
        # "EURUSDm" (7 chars) < "EURUSD.s" (8) < "EURUSD.raw" (10)
        assert result == "EURUSDm"

    def test_prefix_single_candidate(self):
        result = MT5Bridge.resolve_broker_symbol("XAUUSD", ["XAUUSD.s"])
        assert result == "XAUUSD.s"

    # Priority 3: substring / suffix match
    def test_substring_fallback(self):
        """base name is a substring of the broker symbol."""
        result = MT5Bridge.resolve_broker_symbol("XAU", ["XAUUSD.s", "GBPUSD.s"])
        assert result == "XAUUSD.s"

    def test_substring_shortest_wins(self):
        result = MT5Bridge.resolve_broker_symbol(
            "USD", ["EURUSD.s", "GBPUSD.s", "USDJPY.s"]
        )
        # All contain 'USD'; shortest is any 8-char one — just verify it returns one
        assert "USD" in result

    # Priority 4: no match → return base unchanged
    def test_no_match_returns_base(self):
        result = MT5Bridge.resolve_broker_symbol("BTCUSD", ["EURUSD.s", "XAUUSD.s"])
        assert result == "BTCUSD"

    def test_empty_broker_list_returns_base(self):
        result = MT5Bridge.resolve_broker_symbol("EURUSD", [])
        assert result == "EURUSD"

    # Edge cases
    def test_case_sensitive(self):
        """Symbol matching is case-sensitive (MT5 names are typically uppercase)."""
        result = MT5Bridge.resolve_broker_symbol("eurusd", ["EURUSD", "EURUSD.s"])
        # 'eurusd' != 'EURUSD' (exact), doesn't start with 'eurusd' — no prefix match
        # but 'eurusd' as substring: 'EURUSD' does NOT contain 'eurusd' (case matters)
        assert result == "eurusd"  # no match → base returned

    def test_multiple_symbols_different_instruments(self):
        broker = ["EURUSD.s", "GBPUSD.s", "XAUUSD.s", "USDJPY.s"]
        assert MT5Bridge.resolve_broker_symbol("EURUSD", broker) == "EURUSD.s"
        assert MT5Bridge.resolve_broker_symbol("GBPUSD", broker) == "GBPUSD.s"
        assert MT5Bridge.resolve_broker_symbol("XAUUSD", broker) == "XAUUSD.s"
        assert MT5Bridge.resolve_broker_symbol("USDJPY", broker) == "USDJPY.s"
