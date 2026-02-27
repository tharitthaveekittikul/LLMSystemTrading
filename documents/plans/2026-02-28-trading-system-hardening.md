# Trading System Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the live trading system with runtime risk enforcement, LLM position memory, news context injection, paper trading mode, and Telegram alerting.

**Architecture:** Five independent capability additions to the existing FastAPI + LangChain + MT5 stack. No breaking changes — each builds on existing patterns. Execution order matters: risk enforcement first (safety), then intelligence improvements (memory, news), then operational tools (paper trading, alerts).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy + Alembic, LangChain, httpx (already installed), Telegram Bot API.

---

## Task 1: Create `services/risk_manager.py` with Pure Functions

**Files:**
- Create: `backend/services/risk_manager.py`
- Create: `backend/tests/test_risk_manager.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_risk_manager.py
from services.risk_manager import exceeds_position_limit, exceeds_drawdown_limit


def test_position_limit_not_exceeded():
    positions = [{"ticket": 1}, {"ticket": 2}]
    exceeded, reason = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is False
    assert reason == ""


def test_position_limit_exactly_at_max():
    positions = [{"ticket": i} for i in range(5)]
    exceeded, reason = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is True
    assert "5/5" in reason


def test_position_limit_exceeded():
    positions = [{"ticket": i} for i in range(6)]
    exceeded, _ = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is True


def test_drawdown_not_exceeded():
    exceeded, reason = exceeds_drawdown_limit(equity=9500.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is False
    assert reason == ""


def test_drawdown_exactly_at_limit():
    # 10000 - 9000 = 1000 loss = 10% drawdown
    exceeded, reason = exceeds_drawdown_limit(equity=9000.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is True
    assert "10.00%" in reason


def test_drawdown_exceeded():
    exceeded, _ = exceeds_drawdown_limit(equity=8000.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is True


def test_drawdown_zero_balance_safe():
    # Guard against division by zero
    exceeded, _ = exceeds_drawdown_limit(equity=0.0, balance=0.0, max_drawdown_pct=10.0)
    assert exceeded is False
```

**Step 2: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_risk_manager.py -v
```
Expected: `ImportError` — `services.risk_manager` does not exist.

**Step 3: Implement `risk_manager.py`**

```python
# backend/services/risk_manager.py
"""Runtime risk checks — pure functions with no I/O side effects.

Position count gate: call before placing an order.
Drawdown monitor: call from equity poller after each equity update.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def exceeds_position_limit(
    positions: list[dict[str, Any]], max_positions: int
) -> tuple[bool, str]:
    """Return (exceeded, reason). True means limit hit — order should be rejected."""
    count = len(positions)
    if count >= max_positions:
        reason = f"Position limit reached: {count}/{max_positions} open positions"
        logger.warning(reason)
        return True, reason
    return False, ""


def exceeds_drawdown_limit(
    equity: float, balance: float, max_drawdown_pct: float
) -> tuple[bool, str]:
    """Return (exceeded, reason). True means drawdown limit breached — kill switch should fire.

    Drawdown is measured as (balance - equity) / balance * 100.
    A drawdown >= max_drawdown_pct triggers the limit.
    """
    if balance <= 0:
        return False, ""
    drawdown_pct = (balance - equity) / balance * 100
    if drawdown_pct >= max_drawdown_pct:
        reason = (
            f"Max drawdown exceeded: {drawdown_pct:.2f}% >= {max_drawdown_pct:.1f}% "
            f"(equity={equity:.2f}, balance={balance:.2f})"
        )
        logger.warning(reason)
        return True, reason
    return False, ""
```

**Step 4: Run tests to confirm they pass**

```bash
cd backend && uv run pytest tests/test_risk_manager.py -v
```
Expected: 7 tests PASSED.

---

## Task 2: Position Count Gate in `mt5/executor.py`

**Files:**
- Modify: `backend/mt5/executor.py`
- Modify: `backend/tests/test_risk_manager.py` (add executor integration test)

**Step 1: Add integration test for position gate**

Append to `backend/tests/test_risk_manager.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from mt5.executor import MT5Executor, OrderRequest, OrderResult


def _make_order() -> OrderRequest:
    return OrderRequest(
        symbol="EURUSD",
        direction="BUY",
        volume=0.1,
        entry_price=1.0850,
        stop_loss=1.0800,
        take_profit=1.0950,
    )


@pytest.mark.asyncio
async def test_executor_rejects_when_position_limit_hit():
    """place_order must return failure when max open positions is reached."""
    mock_bridge = AsyncMock()
    # Simulate 5 open positions (at the limit)
    mock_bridge.get_positions.return_value = [{"ticket": i} for i in range(5)]

    executor = MT5Executor(bridge=mock_bridge)

    with patch("mt5.executor.kill_switch_active", return_value=False):
        with patch("mt5.executor.settings") as mock_settings:
            mock_settings.max_open_positions = 5
            result = await executor.place_order(_make_order())

    assert result.success is False
    assert "Position limit" in result.error
    mock_bridge.send_order.assert_not_called()
```

**Step 2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_risk_manager.py::test_executor_rejects_when_position_limit_hit -v
```
Expected: FAIL — position check not implemented in executor yet.

**Step 3: Modify `backend/mt5/executor.py`**

Add these two imports near the top (after existing imports):

```python
from core.config import settings
from services.risk_manager import exceeds_position_limit
```

In `place_order()`, after the kill switch gate (after line 67, before line 69 `logger.info("Placing order..."`), add:

```python
        # ── Position count gate ───────────────────────────────────────────────
        try:
            open_positions = await self._bridge.get_positions()
        except Exception as exc:
            logger.warning("Could not fetch positions for limit check: %s", exc)
            open_positions = []

        exceeded, reason = exceeds_position_limit(open_positions, settings.max_open_positions)
        if exceeded:
            logger.warning(
                "Order rejected — %s | symbol=%s direction=%s",
                reason, request.symbol, request.direction,
            )
            return OrderResult(success=False, error=reason)
```

**Step 4: Run tests to confirm they pass**

```bash
cd backend && uv run pytest tests/test_risk_manager.py -v
```
Expected: all tests PASSED.

**Step 5: Run full test suite — no regressions**

```bash
cd backend && uv run pytest -v
```
Expected: all existing tests still PASS.

---

## Task 3: Drawdown Monitor in `services/equity_poller.py`

**Files:**
- Modify: `backend/services/equity_poller.py`
- Modify: `backend/tests/test_equity_poller.py` (add drawdown test)

**Step 1: Review existing equity poller test**

Read `backend/tests/test_equity_poller.py` to understand existing test helpers before adding.

**Step 2: Add drawdown trigger test**

Append to `backend/tests/test_equity_poller.py`:

```python
@pytest.mark.asyncio
async def test_poll_account_activates_kill_switch_on_drawdown(monkeypatch):
    """Drawdown >= max_drawdown_percent must activate the kill switch."""
    import services.kill_switch as ks

    monkeypatch.setattr(ks, "_persist", lambda *a, **k: _noop())
    monkeypatch.setattr(ks, "_broadcast_kill_switch", lambda *a, **k: _noop())
    monkeypatch.setattr(ks, "_active", False)

    # equity = 8000, balance = 10000 → 20% drawdown, threshold is 10%
    mock_info = {
        "equity": 8000.0, "balance": 10000.0,
        "margin": 0.0, "margin_free": 8000.0,
        "margin_level": 0.0, "currency": "USD",
    }

    inserted = []
    broadcasts = []

    from services.equity_poller import _poll_account
    with patch("services.equity_poller.settings") as mock_cfg:
        mock_cfg.mt5_path = ""
        mock_cfg.max_drawdown_percent = 10.0

        with patch("services.equity_poller.MT5Bridge") as mock_bridge_cls:
            mock_bridge = AsyncMock()
            mock_bridge.get_account_info.return_value = mock_info
            mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

            account = {"id": 99, "login": 1, "password_encrypted": "x", "server": "srv"}
            with patch("services.equity_poller.decrypt", return_value="pass"):
                await _poll_account(account, lambda **k: inserted.append(k), lambda *a, **k: broadcasts.append(k))

    assert ks.is_active() is True
    # Clean up
    await ks.deactivate()
```

Note: you'll need `from unittest.mock import AsyncMock, patch` at the top of the test file if not already present.

**Step 3: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_equity_poller.py::test_poll_account_activates_kill_switch_on_drawdown -v
```
Expected: FAIL — drawdown check not in equity_poller yet.

**Step 4: Modify `backend/services/equity_poller.py`**

Add imports at top (after existing imports):

```python
from core.config import settings
from services.risk_manager import exceeds_drawdown_limit
```

In `_poll_account()`, after the `equity = float(...)` block (after `margin_level` line, before `await insert_fn(...)`), add:

```python
        # ── Drawdown monitor ─────────────────────────────────────────────────
        from services.kill_switch import is_active, activate  # local import avoids circular

        if not is_active():
            exceeded, reason = exceeds_drawdown_limit(equity, balance, settings.max_drawdown_percent)
            if exceeded:
                await activate(reason, triggered_by="equity_poller")
```

**Step 5: Run tests**

```bash
cd backend && uv run pytest tests/test_equity_poller.py -v && uv run pytest -v
```
Expected: all PASSED.

---

## Task 4: LLM Position Memory — Update Orchestrator Prompt

**Files:**
- Modify: `backend/ai/orchestrator.py`

**Step 1: Write tests for position memory in prompt**

Create `backend/tests/test_orchestrator.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from ai.orchestrator import TradingSignal, analyze_market


def _mock_signal_dict() -> dict:
    return {
        "action": "BUY",
        "entry": 1.085,
        "stop_loss": 1.080,
        "take_profit": 1.095,
        "confidence": 0.85,
        "rationale": "Strong uptrend",
        "timeframe": "M15",
    }


@pytest.mark.asyncio
async def test_analyze_market_returns_trading_signal():
    """analyze_market returns a validated TradingSignal."""
    with patch("ai.orchestrator._build_llm") as mock_llm_factory:
        mock_chain_result = AsyncMock(return_value=_mock_signal_dict())
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm

        with patch("ai.orchestrator._PROMPT") as mock_prompt:
            mock_chain = AsyncMock()
            mock_chain.ainvoke = AsyncMock(return_value=_mock_signal_dict())
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.__or__ = MagicMock(return_value=mock_chain)

            with patch("ai.orchestrator.settings") as mock_cfg:
                mock_cfg.llm_provider = "openai"
                mock_cfg.llm_confidence_threshold = 0.70
                mock_cfg.openai_api_key = "test"

                result = await analyze_market(
                    symbol="EURUSD",
                    timeframe="M15",
                    current_price=1.085,
                    indicators={"sma_20": 1.083},
                    ohlcv=[{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}] * 20,
                )

    assert isinstance(result, TradingSignal)


@pytest.mark.asyncio
async def test_analyze_market_with_positions_and_signals():
    """analyze_market accepts open_positions and recent_signals without error."""
    open_positions = [{"symbol": "EURUSD", "direction": "BUY", "volume": 0.1, "profit": 50.0}]
    recent_signals = [{"symbol": "EURUSD", "signal": "BUY", "confidence": 0.9, "rationale": "prior reason"}]

    with patch("ai.orchestrator._build_llm"):
        with patch("ai.orchestrator._PROMPT") as mock_prompt:
            mock_chain = AsyncMock()
            mock_chain.ainvoke = AsyncMock(return_value=_mock_signal_dict())
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.__or__ = MagicMock(return_value=mock_chain)

            with patch("ai.orchestrator.settings") as mock_cfg:
                mock_cfg.llm_provider = "openai"
                mock_cfg.llm_confidence_threshold = 0.70
                mock_cfg.openai_api_key = "test"

                # Must not raise
                result = await analyze_market(
                    symbol="EURUSD",
                    timeframe="M15",
                    current_price=1.085,
                    indicators={},
                    ohlcv=[],
                    open_positions=open_positions,
                    recent_signals=recent_signals,
                )
    assert result.action in {"BUY", "SELL", "HOLD"}
```

**Step 2: Run tests**

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v
```
Expected: Both tests may pass or fail depending on mock chain setup — note failures for after implementation.

**Step 3: Modify `backend/ai/orchestrator.py`**

Replace the `_SYSTEM` constant (lines 68–86), `_HUMAN` constant (lines 88–98), and `analyze_market` signature (lines 105–154) with:

```python
_SYSTEM = """You are a professional forex and commodity trading analyst.
Analyze the provided market data and return ONLY a JSON trading signal.

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or when risk/reward is unfavorable.
- Stop loss and take profit must be logical relative to current price and ATR.
- Confidence reflects your conviction based on indicator confluence (0.0 = none, 1.0 = certain).
- CRITICAL: Check your currently open positions before signaling. Avoid doubling into the same direction
  unless confluence is extremely strong (confidence > 0.90). Never open opposing positions simultaneously.

Return strictly valid JSON matching this schema:
{{
  "action": "BUY | SELL | HOLD",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<brief 1-2 sentence explanation>",
  "timeframe": "<e.g. M15>"
}}"""

_HUMAN = """Symbol: {symbol}
Timeframe: {timeframe}
Current Price: {current_price}

Indicators:
{indicators}

Last 20 OHLCV candles (oldest → newest):
{ohlcv}
{positions_section}
{signals_section}
{chart_section}
{news_section}
Provide the trading signal JSON."""

_PROMPT = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])


# ── Public API ────────────────────────────────────────────────────────────────

async def analyze_market(
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict[str, Any],
    ohlcv: list[dict[str, Any]],
    chart_analysis: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    recent_signals: list[dict[str, Any]] | None = None,
    news_context: str | None = None,
) -> TradingSignal:
    """Run the full LLM analysis pipeline and return a validated TradingSignal.

    If confidence is below the configured threshold the action is forced to HOLD.
    """
    logger.info(
        "Analyzing market | provider=%s symbol=%s timeframe=%s price=%s",
        settings.llm_provider, symbol, timeframe, current_price,
    )

    llm = _build_llm()
    chain = _PROMPT | llm | JsonOutputParser()

    chart_section = (
        f"\nChart Pattern Analysis:\n{chart_analysis}" if chart_analysis else ""
    )

    if open_positions:
        pos_lines = [
            f"  - {p.get('symbol', symbol)} {p.get('direction', '?')} "
            f"vol={p.get('volume', '?')} profit={p.get('profit', '?')}"
            for p in open_positions
        ]
        positions_section = "\nCurrently Open Positions:\n" + "\n".join(pos_lines)
    else:
        positions_section = "\nCurrently Open Positions: None"

    if recent_signals:
        sig_lines = [
            f"  - {s.get('symbol', symbol)} {s.get('signal', '?')} "
            f"conf={s.get('confidence', '?')} | {s.get('rationale', '')[:80]}"
            for s in recent_signals
        ]
        signals_section = "\nRecent Signal History (newest first):\n" + "\n".join(sig_lines)
    else:
        signals_section = ""

    news_section = f"\n{news_context}" if news_context else ""

    raw: dict = await chain.ainvoke(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "indicators": json.dumps(indicators, indent=2),
            "ohlcv": json.dumps(ohlcv[-20:], indent=2, default=str),
            "chart_section": chart_section,
            "positions_section": positions_section,
            "signals_section": signals_section,
            "news_section": news_section,
        }
    )

    signal = TradingSignal(**raw)

    # Confidence gate — downgrade low-confidence signals to HOLD
    if signal.confidence < settings.llm_confidence_threshold:
        logger.info(
            "Signal downgraded to HOLD — confidence %.2f below threshold %.2f | symbol=%s",
            signal.confidence, settings.llm_confidence_threshold, symbol,
        )
        signal.action = "HOLD"

    logger.info(
        "Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
        symbol, signal.action, signal.confidence, signal.timeframe,
    )
    return signal
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_orchestrator.py tests/test_ai_trading.py -v
```
Expected: all PASSED.

---

## Task 5: LLM Position Memory — Wire into AI Trading Service

**Files:**
- Modify: `backend/services/ai_trading.py`

**Step 1: Write test for position context passing**

Append to `backend/tests/test_ai_trading.py`:

```python
@pytest.mark.asyncio
async def test_analyze_passes_positions_to_llm():
    """analyze_and_trade passes open_positions to analyze_market."""
    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        max_lot_size=0.1, is_active=True, auto_trade_enabled=False,
        paper_trade_enabled=False,
        allowed_symbols="",
    )
    # Simulate the DB returning 2 recent journal entries
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    mock_positions = [{"symbol": "EURUSD", "direction": "BUY", "volume": 0.1, "profit": 25.0}]
    captured = {}

    async def mock_analyze(**kwargs):
        captured.update(kwargs)
        return _make_signal("HOLD")

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=True),
        patch("services.ai_trading.get_candle_cache", return_value=None),
        patch("services.ai_trading.set_candle_cache"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        patch("services.ai_trading.analyze_market", side_effect=mock_analyze),
        patch("services.ai_trading.broadcast"),
        patch("services.ai_trading.decrypt", return_value="password"),
        patch("services.ai_trading.settings") as mock_cfg,
    ):
        mock_cfg.mt5_path = ""
        mock_cfg.llm_provider = "openai"
        mock_cfg.news_enabled = False

        mock_bridge = AsyncMock()
        mock_bridge.get_rates.return_value = [
            {"time": "t", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}
        ] * 20
        mock_bridge.get_tick.return_value = {"bid": 1.085, "ask": 1.086}
        mock_bridge.get_positions.return_value = mock_positions
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        from services.ai_trading import AITradingService
        service = AITradingService()
        await service.analyze_and_trade(account_id=1, symbol="EURUSD", timeframe="M15", db=mock_db)

    assert "open_positions" in captured
    assert len(captured["open_positions"]) == 1
```

**Step 2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_ai_trading.py::test_analyze_passes_positions_to_llm -v
```
Expected: FAIL — open_positions not yet passed.

**Step 3: Modify `backend/services/ai_trading.py`**

Add these imports at the top (after existing imports):

```python
from sqlalchemy import select, desc
```

Replace the `analyze_and_trade` method's step 6 "LLM analysis" block (lines ~129–136) with:

```python
        # 6. Fetch position context and recent signals for LLM memory
        open_positions: list[dict] = []
        try:
            password_for_positions = decrypt(account.password_encrypted)
            creds_for_positions = AccountCredentials(
                login=account.login,
                password=password_for_positions,
                server=account.server,
                path=settings.mt5_path,
            )
            async with MT5Bridge(creds_for_positions) as pos_bridge:
                raw_positions = await pos_bridge.get_positions()
            open_positions = [
                {
                    "symbol": p.get("symbol", ""),
                    "direction": "BUY" if p.get("type") == 0 else "SELL",
                    "volume": p.get("volume", 0),
                    "profit": p.get("profit", 0),
                    "ticket": p.get("ticket", 0),
                }
                for p in raw_positions
            ]
        except Exception as exc:
            logger.warning("Could not fetch positions for LLM context | account_id=%s: %s", account_id, exc)

        # Fetch last 5 signals for this account/symbol from AIJournal
        recent_signals: list[dict] = []
        try:
            journal_rows = (
                await db.execute(
                    select(AIJournal)
                    .where(AIJournal.account_id == account_id, AIJournal.symbol == symbol)
                    .order_by(desc(AIJournal.created_at))
                    .limit(5)
                )
            ).scalars().all()
            recent_signals = [
                {
                    "symbol": j.symbol,
                    "signal": j.signal,
                    "confidence": j.confidence,
                    "rationale": j.rationale[:120],
                }
                for j in journal_rows
            ]
        except Exception as exc:
            logger.warning("Could not fetch recent signals for LLM context | account_id=%s: %s", account_id, exc)

        # 6b. Fetch news context (if enabled)
        news_context_str: str | None = None
        if getattr(settings, "news_enabled", False):
            from services.market_context import fetch_upcoming_events, format_news_context
            events = await fetch_upcoming_events([symbol])
            news_context_str = format_news_context(events) or None

        # 7. LLM analysis
        signal = await analyze_market(
            symbol=symbol,
            timeframe=tf_upper,
            current_price=current_price or 0,
            indicators=indicators,
            ohlcv=candles,
            open_positions=open_positions,
            recent_signals=recent_signals,
            news_context=news_context_str,
        )
```

Note: The old "7. Persist AIJournal" block numbering shifts by one — renumber the comments in the file accordingly (7→8, 8→9, etc.).

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_ai_trading.py -v
```
Expected: all PASSED (including new test).

**Step 5: Full suite**

```bash
cd backend && uv run pytest -v
```
Expected: all PASSED.

---

## Task 6: News/Macro Context Engine

**Files:**
- Create: `backend/services/market_context.py`
- Create: `backend/tests/test_market_context.py`
- Modify: `backend/core/config.py`

**Step 1: Add `news_enabled` config setting**

In `backend/core/config.py`, add to the `# ── Application ──` section:

```python
    news_enabled: bool = False  # Set to True + configure in .env to enable ForexFactory feed
```

**Step 2: Write failing tests for market_context**

```python
# backend/tests/test_market_context.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
    """Only events for currencies in the given symbols are returned."""
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

    # Only EUR and USD currencies should match — JPY should be filtered
    currencies = {e["currency"] for e in result}
    assert "EUR" in currencies
    assert "JPY" not in currencies
```

**Step 3: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_market_context.py -v
```
Expected: ImportError — module doesn't exist yet.

**Step 4: Create `backend/services/market_context.py`**

```python
# backend/services/market_context.py
"""Market context — ForexFactory public economic calendar.

Fetches the current week's calendar from the community JSON feed.
Falls back to an empty list on any network or parse error (never raises).

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
    """Return high/medium-impact events for currencies in `symbols`, within `hours_ahead` hours.

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
```

**Step 5: Run tests**

```bash
cd backend && uv run pytest tests/test_market_context.py -v && uv run pytest -v
```
Expected: all PASSED.

---

## Task 7: Paper Trading Mode — Model Fields

**Files:**
- Modify: `backend/db/models.py`
- Create: Alembic migration (auto-generated)

**Step 1: Add fields to models**

In `backend/db/models.py`, add to `Account` (after `auto_trade_enabled` line):

```python
    paper_trade_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
```

Add to `Trade` (after `source` line):

```python
    is_paper_trade: Mapped[bool] = mapped_column(Boolean, default=False)
```

**Step 2: Generate Alembic migration**

```bash
cd backend && uv run alembic revision --autogenerate -m "add_paper_trade_fields"
```
Expected: creates a new file in `alembic/versions/` — verify it contains `paper_trade_enabled` and `is_paper_trade` columns.

**Step 3: Apply migration**

```bash
cd backend && uv run alembic upgrade head
```
Expected: `Running upgrade ... -> <new_id>, add_paper_trade_fields`

---

## Task 8: Paper Trading Mode — Executor `dry_run`

**Files:**
- Modify: `backend/mt5/executor.py`
- Modify: `backend/tests/test_risk_manager.py` (add dry_run tests)

**Step 1: Write dry_run tests**

Append to `backend/tests/test_risk_manager.py`:

```python
@pytest.mark.asyncio
async def test_executor_dry_run_does_not_call_bridge():
    """dry_run=True must succeed without calling bridge.send_order."""
    mock_bridge = AsyncMock()
    mock_bridge.get_positions.return_value = []

    executor = MT5Executor(bridge=mock_bridge)
    with patch("mt5.executor.kill_switch_active", return_value=False):
        with patch("mt5.executor.settings") as mock_settings:
            mock_settings.max_open_positions = 10
            result = await executor.place_order(_make_order(), dry_run=True)

    assert result.success is True
    assert result.ticket is not None
    assert result.ticket < 0  # simulated ticket is negative
    mock_bridge.send_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_dry_run_close_does_not_call_bridge():
    """dry_run=True on close_position must succeed without MT5 call."""
    mock_bridge = AsyncMock()

    executor = MT5Executor(bridge=mock_bridge)
    with patch("mt5.executor.kill_switch_active", return_value=False):
        result = await executor.close_position(ticket=12345, symbol="EURUSD", volume=0.1, dry_run=True)

    assert result.success is True
    mock_bridge.send_order.assert_not_called()
```

**Step 2: Run to confirm failure**

```bash
cd backend && uv run pytest tests/test_risk_manager.py::test_executor_dry_run_does_not_call_bridge tests/test_risk_manager.py::test_executor_dry_run_close_does_not_call_bridge -v
```
Expected: FAIL — `place_order` has no `dry_run` parameter.

**Step 3: Modify `backend/mt5/executor.py`**

Add import at top:

```python
import time
```

Modify `place_order` signature (line 60):

```python
    async def place_order(self, request: OrderRequest, dry_run: bool = False) -> OrderResult:
```

After the position count gate block (before `logger.info("Placing order...")`), add:

```python
        # ── Paper trading / dry-run mode ──────────────────────────────────────
        if dry_run:
            fake_ticket = -int(time.time())  # negative so it's distinguishable from real tickets
            logger.info(
                "DRY RUN order | symbol=%s direction=%s volume=%s fake_ticket=%s",
                request.symbol, request.direction, request.volume, fake_ticket,
            )
            return OrderResult(success=True, ticket=fake_ticket, retcode=10009)
```

Modify `close_position` signature (line 114):

```python
    async def close_position(self, ticket: int, symbol: str, volume: float, dry_run: bool = False) -> OrderResult:
```

Add dry_run early return after kill switch check in `close_position` (after the kill switch block):

```python
        if dry_run:
            logger.info("DRY RUN close | ticket=%s symbol=%s volume=%s", ticket, symbol, volume)
            return OrderResult(success=True, ticket=ticket, retcode=10009)
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_risk_manager.py -v && uv run pytest -v
```
Expected: all PASSED.

---

## Task 9: Paper Trading Mode — Wire in AI Trading Service

**Files:**
- Modify: `backend/services/ai_trading.py`

**Step 1: Write test**

Append to `backend/tests/test_ai_trading.py`:

```python
@pytest.mark.asyncio
async def test_paper_trade_enabled_uses_dry_run():
    """When account.paper_trade_enabled=True, Trade is saved with is_paper_trade=True."""
    mock_db = AsyncMock()
    account_mock = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        max_lot_size=0.1, is_active=True, auto_trade_enabled=True,
        paper_trade_enabled=True,
        allowed_symbols="",
    )
    mock_db.get.return_value = account_mock
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    placed_orders = []

    async def mock_place_order(req, dry_run=False):
        placed_orders.append({"dry_run": dry_run, "req": req})
        return MagicMock(success=True, ticket=-99999)

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=True),
        patch("services.ai_trading.get_candle_cache", return_value=None),
        patch("services.ai_trading.set_candle_cache"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        patch("services.ai_trading.analyze_market", return_value=_make_signal("BUY")),
        patch("services.ai_trading.broadcast"),
        patch("services.ai_trading.decrypt", return_value="password"),
        patch("services.ai_trading.settings") as mock_cfg,
        patch("services.ai_trading.MT5Executor") as mock_executor_cls,
    ):
        mock_cfg.mt5_path = ""
        mock_cfg.news_enabled = False

        mock_bridge = AsyncMock()
        mock_bridge.get_rates.return_value = [
            {"time": "t", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}
        ] * 20
        mock_bridge.get_tick.return_value = {"bid": 1.085, "ask": 1.086}
        mock_bridge.get_positions.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        mock_executor = AsyncMock()
        mock_executor.place_order = mock_place_order
        mock_executor_cls.return_value = mock_executor

        from services.ai_trading import AITradingService
        service = AITradingService()
        await service.analyze_and_trade(account_id=1, symbol="EURUSD", timeframe="M15", db=mock_db)

    assert len(placed_orders) == 1
    assert placed_orders[0]["dry_run"] is True
```

**Step 2: Run to confirm failure**

```bash
cd backend && uv run pytest tests/test_ai_trading.py::test_paper_trade_enabled_uses_dry_run -v
```
Expected: FAIL — executor not called with `dry_run`.

**Step 3: Modify `backend/services/ai_trading.py`**

In the order execution section (around line 210), change:

```python
                order_result = await executor.place_order(order_req)
```

to:

```python
                order_result = await executor.place_order(
                    order_req, dry_run=account.paper_trade_enabled
                )
```

When persisting the Trade (around line 224), add `is_paper_trade` field:

```python
        trade = Trade(
            account_id=account_id,
            ticket=order_result.ticket,
            symbol=symbol,
            direction=signal.action,
            volume=account.max_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            opened_at=datetime.now(UTC),
            source="ai",
            is_paper_trade=account.paper_trade_enabled,
        )
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_ai_trading.py -v && uv run pytest -v
```
Expected: all PASSED.

---

## Task 10: Telegram Alerting — Core Module

**Files:**
- Create: `backend/services/alerting.py`
- Create: `backend/tests/test_alerting.py`
- Modify: `backend/core/config.py`

**Step 1: Add config settings**

In `backend/core/config.py`, in the `# ── Application ──` section, add:

```python
    # ── Alerting ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = ""    # BotFather token — leave empty to disable
    telegram_chat_id: str = ""      # Target chat/channel ID
```

**Step 2: Write failing tests**

```python
# backend/tests/test_alerting.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.alerting import send_alert


@pytest.mark.asyncio
async def test_send_alert_skips_when_not_configured():
    """send_alert does nothing when token/chat_id are empty."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = ""
        mock_cfg.telegram_chat_id = ""

        with patch("services.alerting.httpx.AsyncClient") as mock_cls:
            await send_alert("test message")
            mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_alert_posts_to_telegram():
    """send_alert calls the Telegram API when configured."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = "test-token"
        mock_cfg.telegram_chat_id = "123456"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("services.alerting.httpx.AsyncClient", return_value=mock_client):
            await send_alert("hello world")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "test-token" in call_kwargs.args[0]  # URL contains token
        assert "hello world" in str(call_kwargs.kwargs)  # message in payload


@pytest.mark.asyncio
async def test_send_alert_silently_handles_network_error():
    """Network failure never raises from send_alert."""
    with patch("services.alerting.settings") as mock_cfg:
        mock_cfg.telegram_bot_token = "token"
        mock_cfg.telegram_chat_id = "123"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with patch("services.alerting.httpx.AsyncClient", return_value=mock_client):
            # Must not raise
            await send_alert("critical error")
```

**Step 3: Run to confirm failure**

```bash
cd backend && uv run pytest tests/test_alerting.py -v
```
Expected: ImportError.

**Step 4: Create `backend/services/alerting.py`**

```python
# backend/services/alerting.py
"""External alerting — Telegram notifications for critical trading events.

Silently skips if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not configured.
Never raises — alerting must not interrupt the trading pipeline.

Usage:
    await send_alert("🚨 Kill switch ACTIVATED: Max drawdown exceeded")
"""
import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_alert(message: str) -> None:
    """Send a Telegram message. No-op if Telegram is not configured."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    url = _TELEGRAM_URL.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.debug("Telegram alert sent | preview=%s", message[:60])
    except Exception as exc:
        logger.warning("Telegram alert failed (non-critical): %s", exc)
```

**Step 5: Run tests**

```bash
cd backend && uv run pytest tests/test_alerting.py -v
```
Expected: 3 tests PASSED.

---

## Task 11: Telegram Alerting — Wire into Kill Switch and AI Trading

**Files:**
- Modify: `backend/services/kill_switch.py`
- Modify: `backend/services/ai_trading.py`

**Step 1: Wire alert into kill switch activation**

In `backend/services/kill_switch.py`, in the `activate()` function, after `await _broadcast_kill_switch(reason=reason)`, add:

```python
        await _send_kill_switch_alert(reason=reason)
```

Add new helper at the bottom of the file (after `_broadcast_kill_switch`):

```python
async def _send_kill_switch_alert(reason: str) -> None:
    """Send Telegram alert on kill switch activation (best effort)."""
    try:
        from services.alerting import send_alert
        await send_alert(f"*KILL SWITCH ACTIVATED*\nReason: {reason}")
    except Exception as exc:
        logger.error("Failed to send kill switch alert: %s", exc)
```

Also wire deactivation alert in `deactivate()`, after `await _persist(...)`:

```python
        await _send_deactivation_alert()
```

Add helper:

```python
async def _send_deactivation_alert() -> None:
    try:
        from services.alerting import send_alert
        await send_alert("*Kill switch DEACTIVATED* — trading resumed")
    except Exception as exc:
        logger.error("Failed to send deactivation alert: %s", exc)
```

**Step 2: Wire alerts into AI trading service**

In `backend/services/ai_trading.py`, add import at top:

```python
from services.alerting import send_alert
```

After the successful trade broadcast (after `await broadcast(account_id, "trade_opened", {...})`), add:

```python
        await send_alert(
            f"*Trade Placed*\n"
            f"Account: {account_id} | {signal.action} {account.max_lot_size} {symbol}\n"
            f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"Ticket: {order_result.ticket}"
            + (" _(paper)_" if account.paper_trade_enabled else "")
        )
```

After a failed order placement (the `logger.error("Order failed...")` line), add:

```python
            await send_alert(
                f"*Order Failed*\n"
                f"Account: {account_id} | {signal.action} {symbol}\n"
                f"Error: {order_result.error}"
            )
```

**Step 3: Verify kill switch tests still pass**

```bash
cd backend && uv run pytest tests/test_kill_switch.py tests/test_kill_switch_routes.py -v
```
Expected: all PASSED (monkeypatching in existing tests isolates `_persist` and `_broadcast_kill_switch`; the new `_send_kill_switch_alert` also needs patching — add it if tests fail).

If kill switch tests fail because `_send_kill_switch_alert` is not monkeypatched, update the existing test:

```python
# In test_kill_switch.py, update the monkeypatch lines:
monkeypatch.setattr(ks, "_persist", lambda *a, **k: _noop())
monkeypatch.setattr(ks, "_broadcast_kill_switch", lambda *a, **k: _noop())
monkeypatch.setattr(ks, "_send_kill_switch_alert", lambda *a, **k: _noop())
monkeypatch.setattr(ks, "_send_deactivation_alert", lambda *a, **k: _noop())
```

**Step 4: Run full test suite**

```bash
cd backend && uv run pytest -v
```
Expected: all tests PASS. No regressions.

---

## Final Verification

**Step 1: Run linter**

```bash
cd backend && uv run ruff check .
```
Expected: no errors.

**Step 2: Run full test suite with coverage**

```bash
cd backend && uv run pytest -v --tb=short
```
Expected: all tests PASS.

**Step 3: Verify Alembic state is clean**

```bash
cd backend && uv run alembic current
```
Expected: shows `head` — no pending migrations.

---

## What was NOT included (deferred)

- **Strategy Configuration UI** (frontend): timeframe/confidence/symbol config per account — deferred, backend already has `allowed_symbols`/`max_lot_size`/`auto_trade_enabled`.
- **Backtesting Engine**: largest remaining effort — needs a full MT5 mock and historical replay harness.
- **LLM Replay Mode**: depends on backtesting engine.
- **Vector DB / RAG**: optional, low priority until trade history is deeper.
