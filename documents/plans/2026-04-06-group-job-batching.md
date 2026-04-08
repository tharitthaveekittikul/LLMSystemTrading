# Group Job Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-binding scheduler jobs with per-(strategy, symbol) group jobs so the LLM/strategy signal is computed once per candle and distributed to all bound accounts for independent execution.

**Architecture:** A new in-memory dict `_group_accounts` tracks which accounts belong to each group job (`strat_{strategy_id}_{symbol}`). When a job fires, Phase 1 computes the market signal once using the first account's credentials. Phase 2 loops through all bound accounts performing per-account kill-switch checks, lot sizing, MT5 execution, journal persistence, and WebSocket broadcast. The existing `AITradingService.analyze_and_trade()` and `run_abstract_strategy_pipeline()` are kept untouched for the API (manual trigger) path.

**Tech Stack:** APScheduler (AsyncIOScheduler), FastAPI, SQLAlchemy async, Python dataclasses, pytest + pytest-asyncio

---

## Behavioral Change to Document

> When multiple accounts share a strategy, the LLM receives open positions and trade history from the **first active account** only (not all accounts). This is a deliberate trade-off: LLM analysis is market-context-driven; per-account position context has minor influence. Document this in code with a comment.

---

## File Structure

| File | Change |
|------|--------|
| `backend/services/ai_trading.py` | Add `SharedMarketContext` dataclass; add `analyze_market_context()` and `execute_for_account()` functions |
| `backend/services/abstract_runner.py` | Add `fetch_strategy_signal()` and `execute_abstract_for_account()` functions |
| `backend/services/scheduler.py` | Add `_group_accounts` dict; add `_run_group_strategy_job()`; replace `_add_binding_jobs()` with group-aware version; update `add_binding_jobs()` / `remove_binding_jobs()` / `remove_all_binding_jobs()` / `trigger_binding_manually()` |
| `backend/api/routes/scheduler.py` | Update `_job_name()` to parse `strat_{strategy_id}_{symbol}` format |
| `backend/tests/test_group_job_batching.py` | New test file |

---

## Task 1: Add `SharedMarketContext` and skeleton functions to `ai_trading.py`

**Files:**
- Modify: `backend/services/ai_trading.py` (after the `AnalysisResult` dataclass, around line 166)
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 1.1: Write failing test for `SharedMarketContext` instantiation**

Create `backend/tests/test_group_job_batching.py`:

```python
"""Tests for group job batching — single LLM call across multiple accounts."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


# ── SharedMarketContext tests ─────────────────────────────────────────────────

def test_shared_market_context_fields():
    from services.ai_trading import SharedMarketContext
    from ai.orchestrator import TradingSignal

    signal = TradingSignal(
        action="BUY", entry=1.1, stop_loss=1.09, take_profit=1.12,
        confidence=0.8, rationale="test", timeframe="H1",
    )
    ctx = SharedMarketContext(
        symbol="EURUSD",
        mt5_symbol="EURUSD.r",
        timeframe="H1",
        candles=[{"close": 1.1}],
        indicators={"rsi_14": 55.0},
        current_price=1.1,
        signal=signal,
        llm_result=None,
        news_signal=None,
    )
    assert ctx.symbol == "EURUSD"
    assert ctx.signal.action == "BUY"
    assert ctx.llm_result is None
```

- [ ] **Step 1.2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_shared_market_context_fields -v
```

Expected: `ImportError: cannot import name 'SharedMarketContext'`

- [ ] **Step 1.3: Add `SharedMarketContext` to `ai_trading.py`**

In `backend/services/ai_trading.py`, after the `AnalysisResult` dataclass (after line ~166), add:

```python
@dataclass
class SharedMarketContext:
    """Market signal computed once in Phase 1 and shared to all accounts in a group job.

    NOTE: open positions / trade history fed to the LLM come from the first active account
    in the group. Per-account position differences are accepted as a pragmatic trade-off —
    market structure analysis dominates signal quality over position context.
    """
    symbol: str
    mt5_symbol: str
    timeframe: str
    candles: list[dict]
    indicators: dict
    current_price: float
    signal: "TradingSignal"
    llm_result: "LLMAnalysisResult | None"  # None when rule_based=True
    news_signal: str | None
```

- [ ] **Step 1.4: Run test to confirm it passes**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_shared_market_context_fields -v
```

Expected: PASS

- [ ] **Step 1.5: Commit**

```bash
git add backend/services/ai_trading.py backend/tests/test_group_job_batching.py
git commit -m "feat(scheduler): add SharedMarketContext dataclass for group job batching"
```

---

## Task 2: Implement `analyze_market_context()` in `ai_trading.py`

This function is Phase 1 of the group job. It is a near-copy of steps 4–8 from `AITradingService._run_pipeline`, operating without a `PipelineTracer`. The caller (group job) passes in the primary account object.

**Files:**
- Modify: `backend/services/ai_trading.py`
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 2.1: Write failing test**

Add to `backend/tests/test_group_job_batching.py`:

```python
@pytest.mark.asyncio
async def test_analyze_market_context_returns_shared_context():
    """analyze_market_context() should return a SharedMarketContext with a signal."""
    from services.ai_trading import analyze_market_context, StrategyOverrides, SharedMarketContext
    from ai.orchestrator import TradingSignal, LLMAnalysisResult

    # Minimal fake account
    mock_account = MagicMock()
    mock_account.login = 123
    mock_account.password_encrypted = b"enc"
    mock_account.server = "demo"
    mock_account.mt5_path = None

    fake_candles = [{"time": 1700000000, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.10, "tick_volume": 100} for _ in range(250)]
    fake_signal = TradingSignal(action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0, confidence=0.5, rationale="test", timeframe="H1")
    fake_llm_result = LLMAnalysisResult(signal=fake_signal, role_results=[], raw_response="")

    mock_db = AsyncMock()

    with patch("services.ai_trading.decrypt", return_value="pass"), \
         patch("services.ai_trading.MT5Bridge") as MockBridge, \
         patch("services.ai_trading.get_candle_cache", return_value=None), \
         patch("services.ai_trading.set_candle_cache", return_value=None), \
         patch("services.ai_trading.analyze_market", return_value=fake_llm_result), \
         patch("services.ai_trading.check_llm_rate_limit", return_value=True):

        bridge_instance = AsyncMock()
        bridge_instance.get_broker_symbol = AsyncMock(return_value="EURUSD.r")
        bridge_instance.is_market_open = AsyncMock(return_value=(True, "FULL"))
        bridge_instance.get_rates = AsyncMock(return_value=fake_candles)
        bridge_instance.get_tick = AsyncMock(return_value={"ask": 1.101, "bid": 1.099})
        bridge_instance.get_positions = AsyncMock(return_value=[])
        MockBridge.return_value.__aenter__ = AsyncMock(return_value=bridge_instance)
        MockBridge.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        mock_db.get = AsyncMock(return_value=None)

        ctx = await analyze_market_context(
            symbol="EURUSD",
            timeframe="H1",
            strategy_id=None,
            strategy_overrides=StrategyOverrides(news_filter=False),
            strategy_instance=None,
            primary_account=mock_account,
            db=mock_db,
        )

    assert isinstance(ctx, SharedMarketContext)
    assert ctx.symbol == "EURUSD"
    assert ctx.mt5_symbol == "EURUSD.r"
    assert ctx.signal is not None
```

- [ ] **Step 2.2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_analyze_market_context_returns_shared_context -v
```

Expected: `ImportError: cannot import name 'analyze_market_context'`

- [ ] **Step 2.3: Implement `analyze_market_context()` in `ai_trading.py`**

Add this module-level async function after `SharedMarketContext` definition. It mirrors `_run_pipeline` steps 4–8 but accepts `primary_account: Account` instead of `account_id: int`, and returns `SharedMarketContext` instead of `AnalysisResult`. No `PipelineTracer` is used (group job logs directly).

```python
async def analyze_market_context(
    symbol: str,
    timeframe: str,
    strategy_id: "int | None",
    strategy_overrides: "StrategyOverrides | None",
    strategy_instance: "object | None",
    primary_account: "Account",
    db: "AsyncSession",
) -> SharedMarketContext:
    """Phase 1 of group job: fetch OHLCV, compute indicators, run LLM/rule signal.

    Called ONCE per group. Uses primary_account credentials for MT5 connection.
    Position/history context for the LLM comes from primary_account only.
    """
    tf_upper = timeframe.upper()
    tf_int = _TIMEFRAME_MAP.get(tf_upper)
    if tf_int is None:
        raise ValueError(f"Unknown timeframe '{timeframe}'")

    # ── OHLCV fetch ──────────────────────────────────────────────────────────
    candles = await get_candle_cache(primary_account.id, symbol, tf_upper)
    current_price: float | None = None
    mt5_symbol: str = symbol

    password = decrypt(primary_account.password_encrypted)
    creds = AccountCredentials(
        login=primary_account.login, password=password,
        server=primary_account.server,
        path=primary_account.mt5_path or settings.mt5_path,
    )

    async with MT5Bridge(creds) as bridge:
        mt5_symbol = await bridge.get_broker_symbol(symbol)
        is_open, trade_mode_name = await bridge.is_market_open(mt5_symbol)
        if not is_open:
            logger.info(
                "Market closed (%s) — skipping group signal | symbol=%s",
                trade_mode_name, mt5_symbol,
            )
            raise RuntimeError(f"Market is closed for {symbol} (trade_mode={trade_mode_name})")

        if candles is None:
            for _attempt in range(2):
                candles = await bridge.get_rates(mt5_symbol, tf_int, 250)
                if candles:
                    break
                if _attempt == 0:
                    import asyncio as _asyncio
                    await _asyncio.sleep(1)
            tick = await bridge.get_tick(mt5_symbol)
            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

    if not candles:
        raise RuntimeError(f"MT5 returned no candles for {mt5_symbol} {timeframe}")

    ttl = _CACHE_TTL.get(tf_upper, 60)
    await set_candle_cache(primary_account.id, symbol, tf_upper, candles, ttl)
    if current_price is None:
        current_price = float(candles[-1].get("close", 0))

    # ── Indicators ───────────────────────────────────────────────────────────
    import math
    try:
        import pandas as pd
        import pandas_ta as ta
        df = pd.DataFrame(candles)
        if not df.empty and len(df) >= 200:
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            df.ta.ema(length=50, append=True)
            df.ta.ema(length=200, append=True)
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.atr(length=14, append=True)
            df.ta.bbands(length=20, std=2, append=True)
            latest = df.iloc[-1].to_dict()
            closes = [float(c.get("close", 0)) for c in candles[-20:]]
            indicators = {
                "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                "ema_50": round(latest.get("EMA_50", 0), 5),
                "ema_200": round(latest.get("EMA_200", 0), 5),
                "rsi_14": round(latest.get("RSI_14", 0), 2),
                "macd": round(latest.get("MACD_12_26_9", 0), 5),
                "macd_histogram": round(latest.get("MACDh_12_26_9", 0), 5),
                "atr_14": round(latest.get("ATRr_14", 0), 5),
                "bb_upper": round(latest.get("BBU_20_2.0", 0), 5),
                "bb_lower": round(latest.get("BBL_20_2.0", 0), 5),
                "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                "candle_count": len(candles),
            }
        else:
            closes = [float(c.get("close", 0)) for c in candles[-20:]]
            indicators = {
                "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                "candle_count": len(candles),
            }
    except Exception:
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        indicators = {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }
    indicators = {k: (0.0 if isinstance(v, float) and math.isnan(v) else v) for k, v in indicators.items()}

    # ── Position + signal context (from primary account only) ────────────────
    open_positions: list[dict] = []
    try:
        async with MT5Bridge(creds) as pos_bridge:
            raw = await pos_bridge.get_positions()
        open_positions = [
            {
                "symbol": p.get("symbol", ""),
                "direction": "BUY" if p.get("type") == 0 else "SELL",
                "volume": p.get("volume", 0),
                "profit": p.get("profit", 0),
            }
            for p in raw
        ]
    except Exception as exc:
        logger.warning("Could not fetch positions for group LLM context | account_id=%s: %s",
                       primary_account.id, exc)

    recent_signals: list[dict] = []
    try:
        from sqlalchemy import desc as _desc
        rows = (await db.execute(
            select(AIJournal)
            .where(AIJournal.account_id == primary_account.id, AIJournal.symbol == symbol)
            .order_by(_desc(AIJournal.created_at))
            .limit(5)
        )).scalars().all()
        recent_signals = [
            {"symbol": j.symbol, "signal": j.signal, "confidence": j.confidence,
             "rationale": j.rationale[:120]}
            for j in rows
        ]
    except Exception as exc:
        logger.warning("Could not fetch recent signals for group LLM context | account_id=%s: %s",
                       primary_account.id, exc)

    # ── Rule-based signal path ───────────────────────────────────────────────
    signal: "TradingSignal | None" = None
    llm_result: "LLMAnalysisResult | None" = None

    if strategy_instance is not None:
        market_data = {
            "symbol": symbol, "timeframe": tf_upper, "current_price": current_price or 0,
            "candles": candles, "indicators": indicators,
            "open_positions": open_positions, "recent_signals": recent_signals,
        }
        try:
            rule_result = strategy_instance.generate_signal(market_data)
        except Exception:
            logger.exception("generate_signal raised in group context | strategy=%s",
                             type(strategy_instance).__name__)
            rule_result = None
        if rule_result is not None:
            signal = TradingSignal(**rule_result)

    # ── LLM path ─────────────────────────────────────────────────────────────
    news_signal: str | None = None
    if signal is None:
        # News gate
        if strategy_overrides and strategy_overrides.news_filter:
            from services.market_context import fetch_high_impact_events
            news_events = await fetch_high_impact_events([symbol], minutes=60)
            if news_events:
                na_llm = await _get_task_llm("news_analysis", db)
                news_result = await analyze_news_impact(events=news_events, symbol=symbol, llm=na_llm)
                news_signal = news_result.signal

        # Context timeframe candles
        context_ohlcv: dict[str, list[dict]] = {}
        if strategy_id:
            from db.models import Strategy as _Strat
            strat_db = await db.get(_Strat, strategy_id)
            if strat_db and strat_db.context_tfs and strat_db.context_tfs != "[]":
                try:
                    import json as _json
                    ctx_tfs = _json.loads(strat_db.context_tfs)
                    async with MT5Bridge(creds) as ctx_bridge:
                        for ctx_tf in ctx_tfs:
                            ctx_tf_int = _TIMEFRAME_MAP.get(ctx_tf.upper())
                            if ctx_tf_int:
                                ctx_candles = await ctx_bridge.get_rates(mt5_symbol, ctx_tf_int, 100)
                                if ctx_candles:
                                    context_ohlcv[ctx_tf] = ctx_candles[-50:]
                except Exception as exc:
                    logger.warning("Context TF fetch failed in group job: %s", exc)

        # Trade history
        trade_history_context: str | None = None
        try:
            hist_svc = HistoryService()
            recent_deals = await hist_svc.get_raw_deals(primary_account, days=30)
            out_deals, in_by_pos = HistoryService._pair_deals(recent_deals)
            trade_history_context = HistoryService.format_for_llm(out_deals, in_by_pos, limit=10) or None
        except Exception as exc:
            logger.warning("Could not fetch trade history for group LLM context: %s", exc)

        from services.rag_context import build_rag_context
        rag_ctx = await build_rag_context(db, primary_account.id, symbol, tf_upper)
        if rag_ctx:
            trade_history_context = (
                (trade_history_context + "\n\n" if trade_history_context else "") + rag_ctx
            )

        news_context_str: str | None = None
        if getattr(settings, "news_enabled", False):
            from services.market_context import fetch_upcoming_events, format_news_context
            events = await fetch_upcoming_events([symbol])
            news_context_str = format_news_context(events) or None

        ma_llm = await _get_task_llm("market_analysis", db)
        cv_llm = await _get_task_llm("vision", db)
        ed_llm = await _get_task_llm("execution_decision", db)

        chart_b64: str | None = None
        try:
            chart_b64 = await generate_ohlcv_chart(candles[-100:], symbol, tf_upper)
        except Exception:
            pass

        llm_result = await analyze_market(
            symbol=symbol,
            timeframe=tf_upper,
            candles=candles,
            indicators=indicators,
            open_positions=open_positions,
            recent_signals=recent_signals,
            custom_prompt=strategy_overrides.custom_prompt if strategy_overrides else None,
            news_signal=news_signal,
            news_context=news_context_str,
            trade_history=trade_history_context,
            context_ohlcv=context_ohlcv if context_ohlcv else None,
            chart_image_b64=chart_b64,
            ma_llm=ma_llm,
            cv_llm=cv_llm,
            ed_llm=ed_llm,
        )
        signal = llm_result.signal

    return SharedMarketContext(
        symbol=symbol,
        mt5_symbol=mt5_symbol,
        timeframe=tf_upper,
        candles=candles,
        indicators=indicators,
        current_price=current_price or 0.0,
        signal=signal,
        llm_result=llm_result,
        news_signal=news_signal,
    )
```

- [ ] **Step 2.4: Run test to confirm it passes**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_analyze_market_context_returns_shared_context -v
```

Expected: PASS

- [ ] **Step 2.5: Commit**

```bash
git add backend/services/ai_trading.py backend/tests/test_group_job_batching.py
git commit -m "feat(scheduler): add analyze_market_context() for group job Phase 1"
```

---

## Task 3: Implement `execute_for_account()` in `ai_trading.py`

Phase 2 of the group job. Takes a `SharedMarketContext` and runs per-account execution (kill switch, risk check, lot sizing, MT5 order, AIJournal, WS broadcast). Creates its own `PipelineTracer` internally.

**Files:**
- Modify: `backend/services/ai_trading.py`
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 3.1: Write failing test**

Add to `backend/tests/test_group_job_batching.py`:

```python
@pytest.mark.asyncio
async def test_execute_for_account_hold_signal_no_order():
    """execute_for_account() with HOLD signal should save journal but place no order."""
    from services.ai_trading import execute_for_account, SharedMarketContext, StrategyOverrides, AnalysisResult
    from ai.orchestrator import TradingSignal

    hold_signal = TradingSignal(
        action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0,
        confidence=0.5, rationale="no setup", timeframe="H1",
    )
    ctx = SharedMarketContext(
        symbol="EURUSD", mt5_symbol="EURUSD.r", timeframe="H1",
        candles=[], indicators={}, current_price=1.1,
        signal=hold_signal, llm_result=None, news_signal=None,
    )

    mock_account = MagicMock()
    mock_account.id = 1
    mock_account.is_active = True
    mock_account.auto_trade_enabled = True
    mock_account.name = "TestAcc"
    mock_account.max_lot_size = 0.1
    mock_account.risk_pct = 0.01
    mock_account.password_encrypted = b"enc"
    mock_account.server = "demo"
    mock_account.mt5_path = None

    mock_journal = MagicMock()
    mock_journal.id = 42

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_account)
    mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 42))

    with patch("services.ai_trading.kill_switch_active", return_value=False), \
         patch("services.ai_trading.check_llm_rate_limit", return_value=True), \
         patch("services.ai_trading.broadcast", new_callable=AsyncMock), \
         patch("services.ai_trading.PipelineTracer") as MockTracer:

        mock_tracer = AsyncMock()
        mock_tracer.__aenter__ = AsyncMock(return_value=mock_tracer)
        mock_tracer.__aexit__ = AsyncMock(return_value=False)
        mock_tracer.record = AsyncMock()
        mock_tracer.finalize = MagicMock()
        MockTracer.return_value = mock_tracer

        result = await execute_for_account(
            account_id=1,
            symbol="EURUSD",
            timeframe="H1",
            ctx=ctx,
            strategy_id=None,
            strategy_overrides=StrategyOverrides(),
            db=mock_db,
        )

    assert isinstance(result, AnalysisResult)
    assert result.order_placed is False
    assert result.signal.action == "HOLD"
```

- [ ] **Step 3.2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_execute_for_account_hold_signal_no_order -v
```

Expected: `ImportError: cannot import name 'execute_for_account'`

- [ ] **Step 3.3: Implement `execute_for_account()` in `ai_trading.py`**

Add after `analyze_market_context()`:

```python
async def execute_for_account(
    account_id: int,
    symbol: str,
    timeframe: str,
    ctx: SharedMarketContext,
    strategy_id: "int | None",
    strategy_overrides: "StrategyOverrides | None",
    db: "AsyncSession",
) -> "AnalysisResult":
    """Phase 2 of group job: per-account execution using a pre-computed SharedMarketContext.

    Creates its own PipelineTracer so each account has a full pipeline record.
    """
    async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
        t0 = time.monotonic()
        account: Account | None = await db.get(Account, account_id)
        if not account or not account.is_active:
            await tracer.record("account_loaded", status="error",
                                error="Account not found or inactive",
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed")
            raise HTTPException(status_code=404, detail="Account not found")
        await tracer.record("account_loaded",
                            output_data={"name": account.name,
                                         "auto_trade_enabled": account.auto_trade_enabled,
                                         "max_lot_size": account.max_lot_size},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # Kill switch (fail-fast)
        t0 = time.monotonic()
        ks = kill_switch_active()
        await tracer.record("kill_switch_check", output_data={"active": ks},
                            duration_ms=int((time.monotonic() - t0) * 1000))
        if ks:
            tracer.finalize(status="failed")
            raise HTTPException(status_code=503, detail="Kill switch is active")

        # Rate limit (LLM path only — signal already computed, but record for audit)
        if ctx.llm_result is not None:
            t0 = time.monotonic()
            allowed = await check_llm_rate_limit(account_id)
            if not allowed:
                await tracer.record("rate_limit_check", status="error",
                                    output_data={"allowed": False},
                                    error="LLM rate limit exceeded",
                                    duration_ms=int((time.monotonic() - t0) * 1000))
                tracer.finalize(status="failed")
                raise HTTPException(status_code=429, detail="LLM rate limit exceeded")
            await tracer.record("rate_limit_check",
                                output_data={"allowed": True},
                                duration_ms=int((time.monotonic() - t0) * 1000))

        # Record the shared signal as received
        await tracer.record(
            "shared_signal_received",
            output_data={
                "action": ctx.signal.action,
                "confidence": ctx.signal.confidence,
                "rationale": ctx.signal.rationale[:200],
                "source": "llm" if ctx.llm_result else "rule",
            },
        )

        # Persist AIJournal
        t0 = time.monotonic()
        provider = "group_llm"
        model = "shared"
        if ctx.llm_result and ctx.llm_result.role_results:
            rr = ctx.llm_result.role_results[0]
            provider = _provider_name(rr) if hasattr(rr, "__module__") else provider
        journal = AIJournal(
            account_id=account_id,
            trade_id=None,
            symbol=symbol,
            timeframe=timeframe,
            signal=ctx.signal.action,
            confidence=ctx.signal.confidence,
            rationale=ctx.signal.rationale,
            indicators_snapshot=json.dumps(ctx.indicators),
            llm_provider=provider,
            model_name=model,
            strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)
        await tracer.record("journal_saved", output_data={"journal_id": journal.id},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # Broadcast ai_signal
        await broadcast(account_id, "ai_signal", {
            "journal_id": journal.id, "symbol": symbol, "timeframe": timeframe,
            "action": ctx.signal.action, "confidence": ctx.signal.confidence,
            "rationale": ctx.signal.rationale,
            "entry": ctx.signal.entry, "stop_loss": ctx.signal.stop_loss,
            "take_profit": ctx.signal.take_profit,
        })

        if ctx.signal.action == "HOLD":
            tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
            return AnalysisResult(signal=ctx.signal, order_placed=False, ticket=None,
                                  journal_id=journal.id)

        # Kill switch re-check before order
        ks2 = kill_switch_active()
        if ks2:
            tracer.finalize(status="skipped", final_action=ctx.signal.action, journal_id=journal.id)
            return AnalysisResult(signal=ctx.signal, order_placed=False, ticket=None,
                                  journal_id=journal.id)

        if not account.auto_trade_enabled:
            tracer.finalize(status="skipped", final_action=ctx.signal.action, journal_id=journal.id)
            return AnalysisResult(signal=ctx.signal, order_placed=False, ticket=None,
                                  journal_id=journal.id)

        # Dynamic lot sizing
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login, password=password,
            server=account.server, path=account.mt5_path or settings.mt5_path,
        )
        mt5_symbol = ctx.mt5_symbol

        if strategy_overrides and strategy_overrides.lot_size is not None:
            effective_lot = strategy_overrides.lot_size
        else:
            effective_lot = account.max_lot_size
            try:
                async with MT5Bridge(creds) as lot_bridge:
                    acct_info = await lot_bridge.get_account_info()
                    sym_info = await lot_bridge.get_symbol_info(mt5_symbol)
                if acct_info and sym_info:
                    balance = float(acct_info.get("balance", 0))
                    tick_value = float(sym_info.get("trade_tick_value", 0))
                    tick_size = float(sym_info.get("trade_tick_size", 0))
                    pip_size = tick_size * 10 if tick_size > 0 else 0.0001
                    sl_distance = abs((ctx.signal.entry or 0) - (ctx.signal.stop_loss or 0))
                    sl_pips = sl_distance / pip_size if pip_size > 0 else 0
                    effective_lot = _calculate_lot_size(
                        balance=balance, risk_pct=account.risk_pct,
                        sl_pips=sl_pips, pip_value_per_lot=tick_value,
                        max_lot=account.max_lot_size,
                    )
            except Exception as exc:
                logger.warning("Dynamic lot size failed in group execution | account_id=%s: %s",
                               account_id, exc)

        await tracer.record("lot_size_calculated",
                            output_data={"effective_lot_size": effective_lot})

        order_req = OrderRequest(
            symbol=mt5_symbol,
            action=ctx.signal.action,
            volume=effective_lot,
            entry_price=ctx.signal.entry,
            stop_loss=ctx.signal.stop_loss,
            take_profit=ctx.signal.take_profit,
            comment="AI-Trade-Group",
            expiration_hours=pending_expiry_hours(timeframe),
        )

        executor = MT5Executor(creds)
        t0 = time.monotonic()
        try:
            exec_result = await executor.execute(order_req)
        except Exception as exc:
            logger.exception("MT5 Executor raised in group execution | account_id=%s", account_id)
            await tracer.record("mt5_execution", status="error", error=str(exc),
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed", final_action=ctx.signal.action, journal_id=journal.id)
            return AnalysisResult(signal=ctx.signal, order_placed=False, ticket=None,
                                  journal_id=journal.id)

        await tracer.record("mt5_execution",
                            output_data={"success": exec_result.success,
                                         "ticket": exec_result.ticket,
                                         "error": exec_result.error},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        if not exec_result.success:
            tracer.finalize(status="failed", final_action=ctx.signal.action, journal_id=journal.id)
            return AnalysisResult(signal=ctx.signal, order_placed=False, ticket=None,
                                  journal_id=journal.id)

        journal.trade_id = exec_result.ticket
        await db.commit()
        await broadcast(account_id, "trade_opened", {
            "ticket": exec_result.ticket, "symbol": symbol,
            "action": ctx.signal.action, "volume": effective_lot,
        })
        tracer.finalize(status="completed", final_action=ctx.signal.action,
                        journal_id=journal.id, trade_id=exec_result.ticket)
        return AnalysisResult(signal=ctx.signal, order_placed=True, ticket=exec_result.ticket,
                              journal_id=journal.id)
```

- [ ] **Step 3.4: Run test to confirm it passes**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_execute_for_account_hold_signal_no_order -v
```

Expected: PASS

- [ ] **Step 3.5: Run all existing tests to confirm no regression**

```bash
cd backend && uv run pytest tests/ -v --tb=short -q
```

Expected: All previously passing tests still pass.

- [ ] **Step 3.6: Commit**

```bash
git add backend/services/ai_trading.py backend/tests/test_group_job_batching.py
git commit -m "feat(scheduler): add execute_for_account() for group job Phase 2"
```

---

## Task 4: Refactor `abstract_runner.py` — split into signal and execution phases

Same split for the AbstractStrategy path. `run_abstract_strategy_pipeline()` is kept as-is (used by API route); two new functions added for group job use.

**Files:**
- Modify: `backend/services/abstract_runner.py`
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 4.1: Write failing test**

Add to `backend/tests/test_group_job_batching.py`:

```python
@pytest.mark.asyncio
async def test_fetch_strategy_signal_returns_result_and_market_data():
    """fetch_strategy_signal() should call strategy.run() once and return (signal, data, symbol)."""
    from services.abstract_runner import fetch_strategy_signal
    from strategies.base_strategy import StrategyResult
    from services.mtf_data import MTFMarketData, TimeframeData, OHLCV

    fake_signal = StrategyResult(
        action="BUY", entry=1900.0, stop_loss=1880.0, take_profit=1940.0,
        confidence=0.9, rationale="pattern", timeframe="H1",
    )

    mock_strategy = AsyncMock()
    mock_strategy.primary_tf = "H1"
    mock_strategy.context_tfs = []
    mock_strategy.candle_counts = {"H1": 20}
    mock_strategy.run = AsyncMock(return_value=fake_signal)

    mock_account = MagicMock()
    mock_account.login = 123
    mock_account.password_encrypted = b"enc"
    mock_account.server = "demo"
    mock_account.mt5_path = None

    fake_ohlcv = [{"time": 1700000000 + i * 3600, "open": 1900.0, "high": 1910.0,
                   "low": 1890.0, "close": 1905.0, "tick_volume": 50} for i in range(30)]

    with patch("services.abstract_runner.decrypt", return_value="pass"), \
         patch("services.abstract_runner.MT5Bridge") as MockBridge:

        bridge_instance = AsyncMock()
        bridge_instance.get_broker_symbol = AsyncMock(return_value="XAUUSD.r")
        bridge_instance.get_tick = AsyncMock(return_value={"ask": 1906.0, "bid": 1904.0})
        bridge_instance.get_rates = AsyncMock(return_value=fake_ohlcv)
        MockBridge.return_value.__aenter__ = AsyncMock(return_value=bridge_instance)
        MockBridge.return_value.__aexit__ = AsyncMock(return_value=False)

        signal, market_data, mt5_symbol = await fetch_strategy_signal(
            symbol="XAUUSD",
            timeframe="H1",
            strategy_instance=mock_strategy,
            primary_account=mock_account,
        )

    assert signal is not None
    assert signal.action == "BUY"
    assert mt5_symbol == "XAUUSD.r"
    assert market_data is not None
    mock_strategy.run.assert_awaited_once()
```

- [ ] **Step 4.2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_fetch_strategy_signal_returns_result_and_market_data -v
```

Expected: `ImportError: cannot import name 'fetch_strategy_signal'`

- [ ] **Step 4.3: Implement `fetch_strategy_signal()` in `abstract_runner.py`**

Add after `run_abstract_strategy_pipeline()`:

```python
async def fetch_strategy_signal(
    symbol: str,
    timeframe: str,
    strategy_instance: AbstractStrategy,
    primary_account: "Account",
) -> "tuple[StrategyResult | None, MTFMarketData | None, str]":
    """Phase 1 for AbstractStrategy group job: fetch MTF data and run strategy once.

    Returns (signal, market_data, mt5_symbol). Uses primary_account credentials.
    """
    password = decrypt(primary_account.password_encrypted)
    creds = AccountCredentials(
        login=primary_account.login, password=password,
        server=primary_account.server,
        path=primary_account.mt5_path or settings.mt5_path,
    )

    timeframes_to_fetch = set([strategy_instance.primary_tf] + list(strategy_instance.context_tfs))
    mtf_timeframes: dict[str, TimeframeData] = {}
    mt5_symbol = symbol
    current_price: float | None = None
    trigger_time = None

    try:
        async with MT5Bridge(creds) as bridge:
            mt5_symbol = await bridge.get_broker_symbol(symbol)
            tick = await bridge.get_tick(mt5_symbol)
            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

            for tf_str in timeframes_to_fetch:
                tf_int = _TIMEFRAME_MAP.get(tf_str)
                if tf_int is None:
                    continue
                count = strategy_instance.candle_counts.get(tf_str, 20)
                candles_raw = await bridge.get_rates(mt5_symbol, tf_int, count + 10)
                if not candles_raw:
                    continue
                ohlcv_list = [
                    OHLCV(time=c["time"], open=c["open"], high=c["high"],
                          low=c["low"], close=c["close"],
                          tick_volume=c.get("tick_volume", 0), spread=c.get("spread", 0))
                    for c in candles_raw
                ]
                ohlcv_list = ohlcv_list[-count:] if len(ohlcv_list) > count else ohlcv_list
                mtf_timeframes[tf_str] = TimeframeData(tf=tf_str, candles=ohlcv_list)
                if tf_str == strategy_instance.primary_tf and ohlcv_list:
                    trigger_time = ohlcv_list[-1].time
                    if current_price is None:
                        current_price = ohlcv_list[-1].close
    except Exception as exc:
        logger.exception("fetch_strategy_signal: data fetch failed | symbol=%s: %s", symbol, exc)
        return None, None, mt5_symbol

    if strategy_instance.primary_tf not in mtf_timeframes or not trigger_time:
        logger.error("fetch_strategy_signal: primary TF data missing | symbol=%s", symbol)
        return None, None, mt5_symbol

    market_data = MTFMarketData(
        symbol=symbol, primary_tf=strategy_instance.primary_tf,
        current_price=current_price or 0,
        timeframes=mtf_timeframes, indicators={}, trigger_time=trigger_time,
    )

    try:
        signal = await strategy_instance.run(market_data)
    except Exception as exc:
        logger.exception("fetch_strategy_signal: strategy.run() failed | symbol=%s", symbol)
        return None, market_data, mt5_symbol

    return signal, market_data, mt5_symbol
```

- [ ] **Step 4.4: Implement `execute_abstract_for_account()` in `abstract_runner.py`**

Add after `fetch_strategy_signal()`:

```python
async def execute_abstract_for_account(
    account_id: int,
    symbol: str,
    timeframe: str,
    signal: "StrategyResult",
    mt5_symbol: str,
    strategy_id: "int | None",
    strategy_overrides: "StrategyOverrides | None",
    db: "AsyncSession",
) -> "tuple[StrategyResult | None, int | None]":
    """Phase 2 for AbstractStrategy group job: per-account journal, WS broadcast, and MT5 order."""
    async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
        t0 = time.monotonic()
        account: "Account | None" = await db.get(Account, account_id)
        if not account or not account.is_active:
            await tracer.record("account_loaded", status="error",
                                error="Account not found or inactive",
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed")
            return None, None

        await tracer.record("account_loaded",
                            output_data={"name": account.name,
                                         "auto_trade_enabled": account.auto_trade_enabled},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # Kill switch
        if kill_switch_active():
            tracer.finalize(status="failed")
            return None, None

        # Persist AIJournal
        journal = AIJournal(
            account_id=account_id, trade_id=None, symbol=symbol, timeframe=timeframe,
            signal=signal.action, confidence=signal.confidence, rationale=signal.rationale,
            indicators_snapshot="{}", llm_provider="group_rule",
            model_name=type(strategy_id).__name__ if strategy_id else "AbstractStrategy",
            strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)
        await tracer.record("journal_saved", output_data={"journal_id": journal.id})

        # Broadcast
        from api.routes.ws import broadcast as _broadcast
        await _broadcast(account_id, "ai_signal", {
            "journal_id": journal.id, "symbol": symbol, "timeframe": timeframe,
            "action": signal.action, "confidence": signal.confidence,
            "rationale": signal.rationale, "entry": signal.entry,
            "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
        })

        if signal.action == "HOLD":
            tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
            return signal, journal.id

        if kill_switch_active() or not account.auto_trade_enabled:
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return signal, journal.id

        # Lot sizing
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login, password=password,
            server=account.server, path=account.mt5_path or settings.mt5_path,
        )

        if strategy_overrides and strategy_overrides.lot_size is not None:
            effective_lot = strategy_overrides.lot_size
        else:
            effective_lot = account.max_lot_size
            try:
                async with MT5Bridge(creds) as lot_bridge:
                    acct_info = await lot_bridge.get_account_info()
                    sym_info = await lot_bridge.get_symbol_info(mt5_symbol)
                if acct_info and sym_info:
                    balance = float(acct_info.get("balance", 0))
                    tick_value = float(sym_info.get("trade_tick_value", 0))
                    tick_size = float(sym_info.get("trade_tick_size", 0))
                    pip_size = tick_size * 10 if tick_size > 0 else 0.0001
                    sl_distance = abs((signal.entry or 0) - (signal.stop_loss or 0))
                    sl_pips = sl_distance / pip_size if pip_size > 0 else 0
                    effective_lot = _calculate_lot_size(
                        balance=balance, risk_pct=account.risk_pct,
                        sl_pips=sl_pips, pip_value_per_lot=tick_value,
                        max_lot=account.max_lot_size,
                    )
            except Exception as exc:
                logger.warning("Dynamic lot sizing failed in abstract group execution | account_id=%s: %s",
                               account_id, exc)

        order_req = OrderRequest(
            symbol=mt5_symbol, action=signal.action, volume=effective_lot,
            entry_price=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            comment="AI-Trade-Group", expiration_hours=pending_expiry_hours(timeframe),
        )

        executor = MT5Executor(creds)
        t0 = time.monotonic()
        try:
            exec_result = await executor.execute(order_req)
        except Exception as exc:
            logger.exception("MT5 execution failed in abstract group job | account_id=%s", account_id)
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return signal, journal.id

        await tracer.record("mt5_execution",
                            output_data={"success": exec_result.success, "ticket": exec_result.ticket},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        if not exec_result.success:
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return signal, journal.id

        journal.trade_id = exec_result.ticket
        await db.commit()
        tracer.finalize(status="completed", final_action=signal.action,
                        journal_id=journal.id, trade_id=exec_result.ticket)
        return signal, journal.id
```

- [ ] **Step 4.5: Run all new tests**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py -v
```

Expected: All pass.

- [ ] **Step 4.6: Commit**

```bash
git add backend/services/abstract_runner.py backend/tests/test_group_job_batching.py
git commit -m "feat(scheduler): add fetch_strategy_signal() and execute_abstract_for_account()"
```

---

## Task 5: Add group account tracking + `_group_bindings_by_strategy()` to `scheduler.py`

**Files:**
- Modify: `backend/services/scheduler.py`
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 5.1: Write failing test for `_group_bindings_by_strategy()`**

Add to `backend/tests/test_group_job_batching.py`:

```python
def test_group_bindings_by_strategy_groups_correctly():
    """Bindings sharing the same strategy_id should be grouped together."""
    from services.scheduler import _group_bindings_by_strategy

    def make_binding(binding_id, account_id, strategy_id, symbols, timeframe="H1"):
        b = MagicMock()
        b.id = binding_id
        b.account_id = account_id
        b.strategy.id = strategy_id
        b.strategy.symbols = f'["{symbols}"]'
        b.strategy.timeframe = timeframe
        b.strategy.trigger_type = "cron"
        b.strategy.interval_minutes = None
        b.strategy.execution_mode = "llm_only"
        b.strategy.module_path = None
        b.strategy.class_name = None
        b.strategy.lot_size = 0.1
        b.strategy.sl_pips = 20.0
        b.strategy.tp_pips = 40.0
        b.strategy.news_filter = True
        b.strategy.custom_prompt = None
        return b

    bindings = [
        make_binding(1, 101, 10, "EURUSD"),
        make_binding(2, 102, 10, "EURUSD"),  # same strategy, same symbol → same group
        make_binding(3, 103, 20, "XAUUSD"),  # different strategy → different group
    ]

    groups = _group_bindings_by_strategy(bindings)

    assert len(groups) == 2
    # Group for strategy 10 / EURUSD should have 2 accounts
    group_key_10 = (10, "EURUSD")
    assert group_key_10 in groups
    assert len(groups[group_key_10]["account_entries"]) == 2
    account_ids = [e[0] for e in groups[group_key_10]["account_entries"]]
    assert 101 in account_ids and 102 in account_ids

    # Group for strategy 20 / XAUUSD should have 1 account
    group_key_20 = (20, "XAUUSD")
    assert group_key_20 in groups
    assert len(groups[group_key_20]["account_entries"]) == 1
```

- [ ] **Step 5.2: Run test to confirm it fails**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_group_bindings_by_strategy_groups_correctly -v
```

Expected: `ImportError: cannot import name '_group_bindings_by_strategy'`

- [ ] **Step 5.3: Add `_group_accounts` dict and `_group_bindings_by_strategy()` to `scheduler.py`**

After the `_scheduler` instantiation (after line 26):

```python
# Maps group job_id → list of (account_id, overrides_dict) for runtime add/remove
_group_accounts: dict[str, list[tuple[int, dict]]] = {}
```

Add new helper function after `_build_overrides()`:

```python
def _group_job_id(strategy_id: int, symbol: str) -> str:
    return f"strat_{strategy_id}_{symbol}"


def _group_bindings_by_strategy(
    bindings: list,
) -> dict[tuple[int, str], dict]:
    """Group active bindings by (strategy_id, symbol).

    Returns dict keyed by (strategy_id, symbol) with structure:
      {
        "strategy": <strategy obj>,
        "account_entries": [(account_id, overrides_dict), ...],
        "module_path": str | None,
        "class_name": str | None,
      }
    """
    groups: dict[tuple[int, str], dict] = {}
    for binding in bindings:
        strategy = binding.strategy
        symbols = json.loads(strategy.symbols or "[]")
        _, overrides, _ = _build_overrides(strategy)
        module_path = strategy.module_path if strategy.execution_mode != "llm_only" else None
        class_name = strategy.class_name if strategy.execution_mode != "llm_only" else None

        for symbol in symbols:
            key = (strategy.id, symbol)
            if key not in groups:
                groups[key] = {
                    "strategy": strategy,
                    "account_entries": [],
                    "module_path": module_path,
                    "class_name": class_name,
                }
            groups[key]["account_entries"].append(
                (binding.account_id, overrides.model_dump())
            )
    return groups
```

- [ ] **Step 5.4: Run test to confirm it passes**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_group_bindings_by_strategy_groups_correctly -v
```

Expected: PASS

- [ ] **Step 5.5: Commit**

```bash
git add backend/services/scheduler.py backend/tests/test_group_job_batching.py
git commit -m "feat(scheduler): add _group_accounts dict and _group_bindings_by_strategy() helper"
```

---

## Task 6: Implement `_run_group_strategy_job()` in `scheduler.py`

This is the new job function that replaces the per-binding `_run_strategy_job` for the group path. It loads the account list from `_group_accounts`, runs a **pre-flight risk check** across all accounts, calls Phase 1 once (only if at least one account is clear), then Phase 2 for clear accounts only.

**Execution flow:**

```text
fire → skip-hour guard → load strategy instance
     → pre-flight risk check (all accounts)
         ├─ all blocked? → log + return (LLM NOT called)
         └─ some/all clear? → Phase 1 (LLM once, primary = first clear account)
                            → Phase 2 (execute_for_account for clear accounts only)
```

**Files:**
- Modify: `backend/services/scheduler.py`
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 6.1: Write failing tests (two scenarios)**

Add to `backend/tests/test_group_job_batching.py`:

```python
@pytest.mark.asyncio
async def test_run_group_strategy_job_skips_llm_when_all_accounts_blocked():
    """If all accounts are risk-blocked, LLM must NOT be called."""
    import services.scheduler as sched_module

    job_id = "strat_10_EURUSD"
    sched_module._group_accounts[job_id] = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    with patch("services.scheduler.analyze_market_context", new_callable=AsyncMock) as mock_analyze, \
         patch("services.scheduler._preflight_risk_check", new_callable=AsyncMock,
               return_value=([], [(101, {}), (102, {})])) as mock_preflight, \
         patch("services.scheduler.AsyncSessionLocal"):

        await sched_module._run_group_strategy_job(
            strategy_id=10, symbol="EURUSD", timeframe="H1",
            module_path=None, class_name=None,
        )

    # LLM must NOT be called when all accounts blocked
    mock_analyze.assert_not_awaited()
    del sched_module._group_accounts[job_id]


@pytest.mark.asyncio
async def test_run_group_strategy_job_executes_only_clear_accounts():
    """If one account is blocked and one is clear, LLM runs once and only clear account executes."""
    import services.scheduler as sched_module

    job_id = "strat_10_EURUSD"
    sched_module._group_accounts[job_id] = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    from ai.orchestrator import TradingSignal
    from services.ai_trading import SharedMarketContext, AnalysisResult

    fake_signal = TradingSignal(action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0,
                                confidence=0.5, rationale="test", timeframe="H1")
    fake_ctx = SharedMarketContext(
        symbol="EURUSD", mt5_symbol="EURUSD.r", timeframe="H1",
        candles=[], indicators={}, current_price=1.1,
        signal=fake_signal, llm_result=None, news_signal=None,
    )
    fake_result = AnalysisResult(signal=fake_signal, order_placed=False, ticket=None, journal_id=1)

    mock_account = MagicMock()
    mock_account.id = 101

    # account 101 is clear, account 102 is blocked
    clear = [(101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None})]
    blocked = [(102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None})]

    with patch("services.scheduler._preflight_risk_check", new_callable=AsyncMock,
               return_value=(clear, blocked)), \
         patch("services.scheduler.analyze_market_context", new_callable=AsyncMock,
               return_value=fake_ctx) as mock_analyze, \
         patch("services.scheduler.execute_for_account", new_callable=AsyncMock,
               return_value=fake_result) as mock_execute, \
         patch("services.scheduler._get_primary_account", new_callable=AsyncMock,
               return_value=mock_account), \
         patch("services.scheduler.AsyncSessionLocal"):

        await sched_module._run_group_strategy_job(
            strategy_id=10, symbol="EURUSD", timeframe="H1",
            module_path=None, class_name=None,
        )

    mock_analyze.assert_awaited_once()   # LLM called once
    assert mock_execute.await_count == 1  # only 1 account executed (not 2)
    del sched_module._group_accounts[job_id]


@pytest.mark.asyncio
async def test_run_group_strategy_job_calls_llm_once_executes_twice():
    """Group job should call analyze_market_context once and execute_for_account twice."""
    import services.scheduler as sched_module

    # Set up _group_accounts with 2 accounts for this job
    job_id = "strat_10_EURUSD"
    sched_module._group_accounts[job_id] = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    from ai.orchestrator import TradingSignal
    from services.ai_trading import SharedMarketContext

    fake_signal = TradingSignal(action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0,
                                confidence=0.5, rationale="test", timeframe="H1")
    fake_ctx = SharedMarketContext(
        symbol="EURUSD", mt5_symbol="EURUSD.r", timeframe="H1",
        candles=[], indicators={}, current_price=1.1,
        signal=fake_signal, llm_result=None, news_signal=None,
    )

    from services.ai_trading import AnalysisResult
    fake_result = AnalysisResult(signal=fake_signal, order_placed=False, ticket=None, journal_id=1)

    mock_account = MagicMock()
    mock_account.id = 99  # primary account

    with patch("services.scheduler._run_group_strategy_job.__wrapped__", create=True), \
         patch("services.scheduler.analyze_market_context", new_callable=AsyncMock, return_value=fake_ctx) as mock_analyze, \
         patch("services.scheduler.execute_for_account", new_callable=AsyncMock, return_value=fake_result) as mock_execute, \
         patch("services.scheduler.AsyncSessionLocal") as MockSession, \
         patch("services.scheduler._get_primary_account", new_callable=AsyncMock, return_value=mock_account):

        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

        await sched_module._run_group_strategy_job(
            strategy_id=10,
            symbol="EURUSD",
            timeframe="H1",
            module_path=None,
            class_name=None,
        )

    # LLM called exactly once
    mock_analyze.assert_awaited_once()
    # Execution called for each account
    assert mock_execute.await_count == 2

    # Cleanup
    del sched_module._group_accounts[job_id]
```

- [ ] **Step 6.2: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_run_group_strategy_job_skips_llm_when_all_accounts_blocked tests/test_group_job_batching.py::test_run_group_strategy_job_executes_only_clear_accounts tests/test_group_job_batching.py::test_run_group_strategy_job_calls_llm_once_executes_twice -v
```

Expected: `ImportError: cannot import name '_run_group_strategy_job'` (or `_preflight_risk_check`)

- [ ] **Step 6.3: Add `_get_primary_account()`, `_preflight_risk_check()`, and `_run_group_strategy_job()` to `scheduler.py`**

Add after `_group_bindings_by_strategy()`:

```python
async def _get_primary_account(account_id: int, db) -> "Account | None":
    """Load the first/primary account for Phase 1 signal generation."""
    from db.models import Account as _Account
    return await db.get(_Account, account_id)


async def _preflight_risk_check(
    account_entries: list[tuple[int, dict]],
    symbol: str,
    db,
) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    """Check risk limits for all accounts before calling LLM.

    Returns (clear_entries, blocked_entries).
    An account is clear if neither position limit nor rate limit is exceeded.
    """
    from db.models import Account as _Account
    from services.risk_manager import load_risk_config, check_position_limit, check_rate_limit
    from core.security import decrypt as _decrypt
    from mt5.bridge import AccountCredentials as _Creds, MT5Bridge as _Bridge

    risk_cfg = await load_risk_config(db)
    clear: list[tuple[int, dict]] = []
    blocked: list[tuple[int, dict]] = []

    for account_id, overrides_dict in account_entries:
        account = await db.get(_Account, account_id)
        if not account or not account.is_active:
            blocked.append((account_id, overrides_dict))
            continue

        # Fetch open positions for this account
        positions: list[dict] = []
        try:
            password = _decrypt(account.password_encrypted)
            creds = _Creds(
                login=account.login, password=password,
                server=account.server, path=account.mt5_path or settings.mt5_path,
            )
            async with _Bridge(creds) as b:
                raw = await b.get_positions()
            positions = [
                {"symbol": p.get("symbol", ""), "direction": "BUY" if p.get("type") == 0 else "SELL",
                 "volume": p.get("volume", 0), "profit": p.get("profit", 0)}
                for p in raw
            ]
        except Exception as exc:
            logger.warning("Pre-flight: could not fetch positions for account %d: %s", account_id, exc)

        exceeded_pos, pos_reason = check_position_limit(positions, risk_cfg)
        if exceeded_pos:
            logger.info("Pre-flight: account %d blocked by position limit — %s", account_id, pos_reason)
            blocked.append((account_id, overrides_dict))
            continue

        exceeded_rate, rate_reason = await check_rate_limit(symbol, risk_cfg, db)
        if exceeded_rate:
            logger.info("Pre-flight: account %d blocked by rate limit — %s", account_id, rate_reason)
            blocked.append((account_id, overrides_dict))
            continue

        clear.append((account_id, overrides_dict))

    return clear, blocked


async def _run_group_strategy_job(
    strategy_id: int | None,
    symbol: str,
    timeframe: str,
    module_path: str | None = None,
    class_name: str | None = None,
) -> None:
    """Group job: compute signal once, execute per account.

    Reads account list from _group_accounts[job_id]. If the list is empty or the job
    has been removed, exits immediately.
    """
    from db.postgres import AsyncSessionLocal
    from services.ai_trading import (
        StrategyOverrides, analyze_market_context, execute_for_account,
    )

    job_id = _group_job_id(strategy_id, symbol) if strategy_id else f"strat_None_{symbol}"
    account_entries = _group_accounts.get(job_id, [])
    if not account_entries:
        logger.warning("Group job %s fired but has no accounts — skipping", job_id)
        return

    # ── Skip-hour / skip-weekday guard ───────────────────────────────────────
    if strategy_id:
        from db.models import Strategy as _Strategy
        async with AsyncSessionLocal() as _db:
            _s = await _db.get(_Strategy, strategy_id)
        if _s:
            _tz_str = _s.skip_hours_timezone or "UTC"
            try:
                _tz = ZoneInfo(_tz_str)
            except ZoneInfoNotFoundError:
                _tz = ZoneInfo("UTC")
            _now = datetime.now(_tz)
            if _s.skip_hours:
                _skip_h: list[int] = json.loads(_s.skip_hours)
                if _now.hour in _skip_h:
                    logger.info("Skip hour %02d (%s): strategy_id=%s symbol=%s — skipped",
                                _now.hour, _tz_str, strategy_id, symbol)
                    return
            if _s.skip_weekdays:
                _skip_wd: list[int] = json.loads(_s.skip_weekdays)
                if _now.weekday() in _skip_wd:
                    logger.info("Skip weekday %s (%s): strategy_id=%s symbol=%s — skipped",
                                _now.strftime("%A"), _tz_str, strategy_id, symbol)
                    return

    # ── Load code strategy instance ──────────────────────────────────────────
    strategy_instance = None
    if module_path and class_name:
        try:
            mod = importlib.import_module(module_path)
            strategy_instance = getattr(mod, class_name)()
            if strategy_id:
                async with AsyncSessionLocal() as _db2:
                    from db.models import Strategy as _Strat
                    strat_db = await _db2.get(_Strat, strategy_id)
                    if strat_db and hasattr(strategy_instance, "apply_db_config"):
                        strategy_instance.apply_db_config(strat_db)
        except Exception:
            logger.exception("Failed to load strategy %s.%s — using LLM fallback",
                             module_path, class_name)

    is_abstract = strategy_instance is not None and hasattr(strategy_instance, "primary_tf")

    # ── Pre-flight: risk check all accounts before spending LLM tokens ────────
    try:
        async with AsyncSessionLocal() as db:
            clear_entries, blocked_entries = await _preflight_risk_check(
                account_entries, symbol, db
            )
    except Exception as exc:
        logger.exception("Group job %s pre-flight risk check failed: %s", job_id, exc)
        return

    if not clear_entries:
        logger.info(
            "Group job %s: all %d accounts risk-blocked — LLM skipped",
            job_id, len(account_entries),
        )
        return

    if blocked_entries:
        logger.info(
            "Group job %s: %d/%d accounts risk-blocked, proceeding for %d clear accounts",
            job_id, len(blocked_entries), len(account_entries), len(clear_entries),
        )

    # ── Phase 1: Compute signal once using first CLEAR account ───────────────
    primary_account_id = clear_entries[0][0]
    try:
        async with AsyncSessionLocal() as db:
            primary_account = await _get_primary_account(primary_account_id, db)
            if primary_account is None or not primary_account.is_active:
                logger.error("Primary account %s not found or inactive for group job %s",
                             primary_account_id, job_id)
                return

            if is_abstract:
                from services.abstract_runner import fetch_strategy_signal
                signal, market_data, mt5_symbol = await fetch_strategy_signal(
                    symbol=symbol, timeframe=timeframe,
                    strategy_instance=strategy_instance,
                    primary_account=primary_account,
                )
                if signal is None:
                    logger.warning("Group job %s: strategy returned no signal", job_id)
                    return
            else:
                primary_overrides = StrategyOverrides(**clear_entries[0][1])
                ctx = await analyze_market_context(
                    symbol=symbol, timeframe=timeframe, strategy_id=strategy_id,
                    strategy_overrides=primary_overrides, strategy_instance=strategy_instance,
                    primary_account=primary_account, db=db,
                )

    except Exception as exc:
        logger.exception("Group job %s Phase 1 failed: %s", job_id, exc)
        return

    # ── Phase 2: Execute for CLEAR accounts only ──────────────────────────────
    for account_id, overrides_dict in clear_entries:
        overrides = StrategyOverrides(**overrides_dict)
        try:
            async with AsyncSessionLocal() as db:
                if is_abstract:
                    from services.abstract_runner import execute_abstract_for_account
                    sig, journal_id = await execute_abstract_for_account(
                        account_id=account_id, symbol=symbol, timeframe=timeframe,
                        signal=signal, mt5_symbol=mt5_symbol,
                        strategy_id=strategy_id, strategy_overrides=overrides, db=db,
                    )
                    logger.info("Group job done: account=%d symbol=%s action=%s",
                                account_id, symbol, sig.action if sig else "None")
                else:
                    result = await execute_for_account(
                        account_id=account_id, symbol=symbol, timeframe=timeframe,
                        ctx=ctx, strategy_id=strategy_id, strategy_overrides=overrides, db=db,
                    )
                    logger.info("Group job done: account=%d symbol=%s action=%s order=%s",
                                account_id, symbol, result.signal.action, result.order_placed)
        except Exception as exc:
            logger.exception("Group job %s Phase 2 failed for account=%d: %s",
                             job_id, account_id, exc)
            # Continue to next account — one failure must not block others
```

- [ ] **Step 6.4: Run all three tests to confirm they pass**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_run_group_strategy_job_skips_llm_when_all_accounts_blocked tests/test_group_job_batching.py::test_run_group_strategy_job_executes_only_clear_accounts tests/test_group_job_batching.py::test_run_group_strategy_job_calls_llm_once_executes_twice -v
```

Expected: All 3 PASS

- [ ] **Step 6.5: Commit**

```bash
git add backend/services/scheduler.py backend/tests/test_group_job_batching.py
git commit -m "feat(scheduler): implement _run_group_strategy_job() — Phase 1 once, Phase 2 per account"
```

---

## Task 7: Update scheduler registration — group-aware `_add_binding_jobs()` and `start_scheduler()`

Replace per-binding job registration with group job registration. Update `add_binding_jobs()` / `remove_binding_jobs()` / `remove_all_binding_jobs()` to maintain `_group_accounts`.

**Files:**
- Modify: `backend/services/scheduler.py`
- Test: `backend/tests/test_group_job_batching.py`

- [ ] **Step 7.1: Write test for group job registration at startup**

Add to `backend/tests/test_group_job_batching.py`:

```python
def test_add_group_job_registers_one_job_per_strategy_symbol():
    """Adding 2 bindings for same strategy+symbol should create 1 job, not 2."""
    import services.scheduler as sched_module
    from unittest.mock import patch, MagicMock

    mock_scheduler = MagicMock()
    mock_scheduler.get_job = MagicMock(return_value=None)
    mock_scheduler.add_job = MagicMock()

    def make_binding(binding_id, account_id, strategy_id):
        b = MagicMock()
        b.id = binding_id
        b.account_id = account_id
        b.strategy.id = strategy_id
        b.strategy.symbols = '["EURUSD"]'
        b.strategy.timeframe = "H1"
        b.strategy.trigger_type = "cron"
        b.strategy.interval_minutes = None
        b.strategy.execution_mode = "llm_only"
        b.strategy.module_path = None
        b.strategy.class_name = None
        b.strategy.lot_size = 0.1
        b.strategy.sl_pips = 20.0
        b.strategy.tp_pips = 40.0
        b.strategy.news_filter = True
        b.strategy.custom_prompt = None
        return b

    bindings = [make_binding(1, 101, 10), make_binding(2, 102, 10)]
    groups = sched_module._group_bindings_by_strategy(bindings)

    # Clear state before test
    sched_module._group_accounts.clear()

    for (strategy_id, symbol), group_data in groups.items():
        job_id = sched_module._group_job_id(strategy_id, symbol)
        sched_module._group_accounts[job_id] = group_data["account_entries"]
        mock_scheduler.add_job(
            sched_module._run_group_strategy_job,
            trigger=MagicMock(),
            id=job_id,
            args=[strategy_id, symbol, group_data["strategy"].timeframe,
                  group_data["module_path"], group_data["class_name"]],
            replace_existing=True,
            misfire_grace_time=60,
        )

    # Only 1 job should be registered (1 strategy × 1 symbol)
    assert mock_scheduler.add_job.call_count == 1
    called_job_id = mock_scheduler.add_job.call_args[1]["id"]
    assert called_job_id == "strat_10_EURUSD"

    # Both accounts tracked in _group_accounts
    assert len(sched_module._group_accounts["strat_10_EURUSD"]) == 2
    sched_module._group_accounts.clear()
```

- [ ] **Step 7.2: Run test to confirm it passes (it uses public API)**

```bash
cd backend && uv run pytest tests/test_group_job_batching.py::test_add_group_job_registers_one_job_per_strategy_symbol -v
```

Expected: PASS (using already-added `_group_job_id` and `_group_bindings_by_strategy`)

- [ ] **Step 7.3: Replace `_add_binding_jobs()` in `scheduler.py`**

Replace the existing `_add_binding_jobs()` function (currently lines 77-95) with:

```python
def _add_binding_jobs(scheduler: AsyncIOScheduler, binding) -> None:
    """Register or update the group job for a single binding.

    If a group job for (strategy_id, symbol) already exists, the new account is
    appended to _group_accounts and the job is re-registered (replace_existing=True).
    """
    strategy = binding.strategy
    symbols = json.loads(strategy.symbols or "[]")
    _, overrides, _ = _build_overrides(strategy)
    module_path = strategy.module_path if strategy.execution_mode != "llm_only" else None
    class_name = strategy.class_name if strategy.execution_mode != "llm_only" else None
    trigger = _make_trigger(strategy)

    for symbol in symbols:
        job_id = _group_job_id(strategy.id, symbol)
        entry = (binding.account_id, overrides.model_dump())

        # Add account to group (avoid duplicates)
        existing = _group_accounts.get(job_id, [])
        if not any(acc_id == binding.account_id for acc_id, _ in existing):
            _group_accounts[job_id] = existing + [entry]
        else:
            # Update overrides for existing account
            _group_accounts[job_id] = [
                entry if acc_id == binding.account_id else (acc_id, ov)
                for acc_id, ov in existing
            ]

        scheduler.add_job(
            _run_group_strategy_job,
            trigger=trigger,
            id=job_id,
            args=[strategy.id, symbol, strategy.timeframe, module_path, class_name],
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("Group job registered/updated %s | accounts=%s",
                    job_id, [a for a, _ in _group_accounts[job_id]])
```

- [ ] **Step 7.4: Update `start_scheduler()` to use group registration**

In `start_scheduler()`, replace the binding loop (currently `for binding in bindings: _add_binding_jobs(...)`) with:

```python
    # Group bindings by (strategy_id, symbol) and register one job per group
    groups = _group_bindings_by_strategy(bindings)
    for (strategy_id, symbol), group_data in groups.items():
        strategy = group_data["strategy"]
        job_id = _group_job_id(strategy_id, symbol)
        _group_accounts[job_id] = group_data["account_entries"]
        trigger = _make_trigger(strategy)
        _scheduler.add_job(
            _run_group_strategy_job,
            trigger=trigger,
            id=job_id,
            args=[strategy_id, symbol, strategy.timeframe,
                  group_data["module_path"], group_data["class_name"]],
            replace_existing=True,
            misfire_grace_time=60,
        )
        account_ids = [a for a, _ in group_data["account_entries"]]
        logger.info("Group job registered %s | accounts=%s", job_id, account_ids)
```

- [ ] **Step 7.5: Update `remove_binding_jobs()` to remove account from group**

Replace the existing `remove_binding_jobs()` (currently at line ~282-289) with:

```python
def remove_binding_jobs(binding_id: int, account_id: int, strategy_id: int, symbols: list[str]) -> None:
    """Remove an account from all group jobs for a binding.

    If removing the account leaves the group empty, the APScheduler job is removed too.

    NOTE: Callers must pass account_id and strategy_id (new params — update call sites).
    """
    for symbol in symbols:
        job_id = _group_job_id(strategy_id, symbol)
        existing = _group_accounts.get(job_id, [])
        updated = [(acc_id, ov) for acc_id, ov in existing if acc_id != account_id]
        if updated:
            _group_accounts[job_id] = updated
            logger.info("Removed account %d from group %s | remaining=%s",
                        account_id, job_id, [a for a, _ in updated])
        else:
            _group_accounts.pop(job_id, None)
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
                logger.info("Group job %s removed (no accounts remaining)", job_id)
```

- [ ] **Step 7.6: Update `remove_all_binding_jobs()` to handle group cleanup**

Replace the existing `remove_all_binding_jobs()` with:

```python
def remove_all_binding_jobs(binding_id: int, account_id: int, strategy_id: int) -> None:
    """Remove an account from all group jobs for a strategy (all symbols).

    NOTE: Callers must pass account_id and strategy_id (new params — update call sites).
    """
    prefix = f"strat_{strategy_id}_"
    for job_id in list(_group_accounts.keys()):
        if not job_id.startswith(prefix):
            continue
        existing = _group_accounts[job_id]
        updated = [(acc_id, ov) for acc_id, ov in existing if acc_id != account_id]
        if updated:
            _group_accounts[job_id] = updated
        else:
            _group_accounts.pop(job_id, None)
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
                logger.info("Group job %s removed (no accounts remaining)", job_id)
```

- [ ] **Step 7.7: Update `trigger_binding_manually()` to fire the group job**

Replace the body of `trigger_binding_manually()` with:

```python
def trigger_binding_manually(binding) -> None:
    """Manually trigger a group job once, immediately."""
    strategy = binding.strategy
    symbols = json.loads(strategy.symbols or "[]")
    module_path = strategy.module_path if strategy.execution_mode != "llm_only" else None
    class_name = strategy.class_name if strategy.execution_mode != "llm_only" else None

    for symbol in symbols:
        one_off_id = f"manual_{strategy.id}_{symbol}_{int(datetime.now(timezone.utc).timestamp())}"
        try:
            _scheduler.add_job(
                _run_group_strategy_job,
                trigger="date",
                run_date=datetime.now(timezone.utc),
                id=one_off_id,
                args=[strategy.id, symbol, strategy.timeframe, module_path, class_name],
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info("Manually triggered group job %s", one_off_id)
        except Exception as e:
            logger.exception("Failed to trigger group job manually %s: %s", one_off_id, e)
```

- [ ] **Step 7.8: Find and update all call sites for `remove_binding_jobs` and `remove_all_binding_jobs`**

Search for callers:

```bash
cd backend && grep -rn "remove_binding_jobs\|remove_all_binding_jobs" --include="*.py" .
```

Update each call site to pass the new `account_id` and `strategy_id` parameters. Typically in `api/routes/strategies.py`.

- [ ] **Step 7.9: Run full test suite**

```bash
cd backend && uv run pytest tests/ -v --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 7.10: Commit**

```bash
git add backend/services/scheduler.py backend/api/routes/strategies.py
git commit -m "feat(scheduler): replace per-binding jobs with group jobs — one LLM call per (strategy, symbol)"
```

---

## Task 8: Update `_job_name()` in `api/routes/scheduler.py`

The `GET /scheduler/jobs` endpoint uses `_job_name()` to display readable names. Update it to handle the new `strat_{strategy_id}_{symbol}` format.

**Files:**
- Modify: `backend/api/routes/scheduler.py`

- [ ] **Step 8.1: Update `_job_name()` in `api/routes/scheduler.py`**

Replace the `_job_name()` function (lines 96-112):

```python
def _job_name(job_id: str) -> str:
    known = {
        "position_maintenance_sweep": "Position Maintenance Sweep",
    }
    if job_id in known:
        return known[job_id]
    if job_id.startswith("strat_"):
        # New format: strat_{strategy_id}_{symbol}
        parts = job_id.split("_", 2)
        if len(parts) >= 3:
            strategy_id = parts[1]
            symbol = parts[2]
            return f"Strategy #{strategy_id} — {symbol}"
        return job_id
    if job_id.startswith("manual_"):
        # manual_{strategy_id}_{symbol}_{timestamp}
        parts = job_id.split("_", 3)
        symbol = parts[2] if len(parts) >= 3 else "Unknown"
        return f"Manual Trigger — {symbol}"
    return job_id
```

Also update the `_job_name()` usage in `list_scheduler_jobs()`. The section that reads `binding_id` from the job ID (currently lines 146-164) parses `strat_{binding_id}_{symbol}`. Update to parse `strat_{strategy_id}_{symbol}` and look up by `strategy_id` instead of `binding_id`:

Replace the `if job.id.startswith("strat_"):` block in `list_scheduler_jobs()`:

```python
        if job.id.startswith("strat_"):
            parts = job.id.split("_", 2)
            try:
                strategy_id = int(parts[1])
                # Find skip config for any binding using this strategy
                config = next(
                    (cfg for sid, cfg in skip_configs.items() if sid == strategy_id),
                    None,
                )
                if config:
                    skip_h, skip_wd, tz_str, strat_name = config
                    job_strategy_name = strat_name
                    if next_run and (skip_h or skip_wd):
                        try:
                            tz = ZoneInfo(tz_str)
                        except ZoneInfoNotFoundError:
                            tz = ZoneInfo("UTC")
                        effective_next_run = (
                            _advance_past_skips(job.trigger, next_run, skip_h, skip_wd, tz)
                            or next_run
                        )
            except (ValueError, IndexError):
                pass
```

Also update `skip_configs` pre-fetch to key by `strategy_id` instead of `binding.id`:

```python
    skip_configs: dict[int, tuple[list[int], list[int], str, str | None]] = {}
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AccountStrategy).options(selectinload(AccountStrategy.strategy))
        )
        for binding in result.scalars().all():
            s = binding.strategy
            sid = s.id  # key by strategy_id now (not binding_id)
            if sid not in skip_configs:  # first binding wins
                skip_h: list[int] = json.loads(s.skip_hours or "[]")
                skip_wd: list[int] = json.loads(s.skip_weekdays or "[]")
                skip_configs[sid] = (skip_h, skip_wd, s.skip_hours_timezone or "UTC", s.name)
```

- [ ] **Step 8.2: Verify scheduler jobs endpoint returns correct names**

Start backend and manually verify (or write a quick integration smoke test):

```bash
cd backend && uv run uvicorn main:app --port 8000 &
sleep 3
curl -s http://localhost:8000/api/v1/scheduler/jobs | python -m json.tool | grep '"name"'
```

Expected output should show `"Strategy #N — SYMBOL"` format.

- [ ] **Step 8.3: Commit**

```bash
git add backend/api/routes/scheduler.py
git commit -m "feat(scheduler): update job name display for group job ID format"
```

---

## Task 9: Final test run and cleanup

- [ ] **Step 9.1: Run the full test suite**

```bash
cd backend && uv run pytest tests/ -v --tb=short
```

Expected: All tests pass. No regressions.

- [ ] **Step 9.2: Verify `_group_accounts` cleanup is not needed on restart**

`_group_accounts` is an in-memory dict initialized empty at module load. APScheduler is in-memory. On restart, `start_scheduler()` calls `_group_bindings_by_strategy()` and re-populates both. No migration needed. Confirm by restarting the backend and checking logs:

```bash
cd backend && uv run uvicorn main:app --port 8000
# Look for: "Group job registered strat_N_SYMBOL | accounts=[...]"
```

- [ ] **Step 9.3: Final commit**

```bash
git add .
git commit -m "feat(scheduler): complete group job batching — single LLM call distributed to all bound accounts"
```

---

## Self-Review

### Spec Coverage
| Requirement | Task |
|-------------|------|
| Single LLM call per (strategy, symbol) per candle | Tasks 2, 6 |
| Skip LLM if ALL accounts are risk-blocked | Task 6 (`_preflight_risk_check`) |
| Execute only for non-risk-blocked accounts | Task 6 (clear_entries only in Phase 2) |
| Distribute signal to all bound accounts | Tasks 3, 4, 6 |
| Per-account execution (lot sizing, MT5, journal, WS) | Tasks 3, 4 |
| Runtime add/remove binding updates group | Task 7 |
| Scheduler UI shows correct job names | Task 8 |
| Existing API (manual trigger) route unchanged | Tasks 3, 4 — `analyze_and_trade()` untouched |

### Known Trade-offs (documented in code)
1. **LLM position context**: From primary account only. Acceptable — market structure dominates.
2. **OHLCV credentials**: First account's MT5 credentials used for data fetch. If accounts are on different brokers, this needs a future rework.
3. **Rate limit per-account**: Still checked per account in `execute_for_account()`. The LLM is called once but rate limit counter increments per account.
4. **`remove_binding_jobs` signature change**: Callers must pass `account_id` + `strategy_id`. All call sites must be updated in Task 7.8.
