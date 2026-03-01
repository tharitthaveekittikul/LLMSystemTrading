# Pipeline Logs — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add full audit traceability to every AI trading pipeline run — every step, its timing, input, and output stored in PostgreSQL and visualised as a live step-by-step timeline in the dashboard.

**Architecture:** Two new DB tables (`pipeline_runs` + `pipeline_steps`) capture each run. A `PipelineTracer` async context manager instruments `ai_trading.py` without changing its logic. A new `/api/v1/pipeline/runs` endpoint serves the data. A new `/logs` frontend page shows a two-panel timeline with live WebSocket updates.

**Tech Stack:** Python/SQLAlchemy (backend models), FastAPI (routes), Alembic (migration), Next.js 16 + TypeScript + Tailwind CSS 4 + shadcn/ui (frontend)

---

## Task 1: Add DB models — `PipelineRun` and `PipelineStep`

**Files:**

- Modify: `backend/db/models.py`

**Step 1: Add the two model classes at the end of `backend/db/models.py`**

Append after the last class (`AccountStrategy`):

```python
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="running")
    # running | completed | hold | skipped | failed
    final_action: Mapped[str | None] = mapped_column(String(10), nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ai_journal.id"), nullable=True
    )
    trade_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("trades.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    steps: Mapped[list["PipelineStep"]] = relationship(
        "PipelineStep", back_populates="run", cascade="all, delete-orphan",
        order_by="PipelineStep.seq",
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))  # ok | skip | error
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="steps")
```

**Step 2: Verify the file is syntactically valid**

```bash
cd backend && uv run python -c "from db.models import PipelineRun, PipelineStep; print('OK')"
```

Expected: `OK`

---

## Task 2: Alembic migration

**Files:**

- Create: `backend/alembic/versions/<hash>_add_pipeline_runs_and_steps.py` (auto-generated)

**Step 1: Generate the migration**

Run from `backend/`:

```bash
cd backend && uv run alembic revision --autogenerate -m "add pipeline_runs and pipeline_steps"
```

Expected: a new file created in `alembic/versions/` with two `create_table` calls for `pipeline_runs` and `pipeline_steps`.

**Step 2: Apply the migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected output ends with: `Running upgrade ... -> <hash>, add pipeline_runs and pipeline_steps`

**Step 3: Verify tables exist**

```bash
cd backend && uv run python -c "
import asyncio
from db.postgres import engine
from sqlalchemy import inspect, text

async def check():
    async with engine.connect() as conn:
        result = await conn.execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_name IN ('pipeline_runs','pipeline_steps')\"))
        print([r[0] for r in result])

asyncio.run(check())
"
```

Expected: `['pipeline_runs', 'pipeline_steps']` (order may vary)

---

## Task 3: Create `PipelineTracer` service

**Files:**

- Create: `backend/services/pipeline_tracer.py`

**Step 1: Write `backend/services/pipeline_tracer.py`**

```python
"""PipelineTracer — records every step of the AI trading pipeline.

Usage:
    async with PipelineTracer(account_id, symbol, timeframe) as tracer:
        t0 = time.monotonic()
        # ... do work ...
        await tracer.record(
            "step_name",
            output_data={"key": "value"},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="completed", final_action="BUY", journal_id=5)

Uses its own DB session (independent of the caller's session) so partial
steps are durable even if the main pipeline session rolls back.
"""
import json
import logging
import time
from typing import Any

from db.models import PipelineRun, PipelineStep
from db.postgres import AsyncSessionLocal

logger = logging.getLogger(__name__)


class PipelineTracer:
    def __init__(self, account_id: int, symbol: str, timeframe: str) -> None:
        self._account_id = account_id
        self._symbol = symbol
        self._timeframe = timeframe
        self._run: PipelineRun | None = None
        self._seq = 0
        self._start_ms = 0.0
        self._final_status = "failed"
        self._final_action: str | None = None
        self._journal_id: int | None = None
        self._trade_id: int | None = None
        self._db = None
        self._session_ctx = None

    async def __aenter__(self) -> "PipelineTracer":
        self._session_ctx = AsyncSessionLocal()
        self._db = await self._session_ctx.__aenter__()
        self._start_ms = time.monotonic()
        self._run = PipelineRun(
            account_id=self._account_id,
            symbol=self._symbol,
            timeframe=self._timeframe,
            status="running",
        )
        self._db.add(self._run)
        await self._db.commit()
        await self._db.refresh(self._run)
        logger.debug(
            "PipelineTracer started | run_id=%s account_id=%s symbol=%s",
            self._run.id, self._account_id, self._symbol,
        )
        return self

    async def record(
        self,
        step_name: str,
        *,
        status: str = "ok",
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Persist a single pipeline step immediately."""
        if not self._run or not self._db:
            return
        self._seq += 1
        step = PipelineStep(
            run_id=self._run.id,
            seq=self._seq,
            step_name=step_name,
            status=status,
            input_json=json.dumps(input_data, default=str) if input_data is not None else None,
            output_json=json.dumps(output_data, default=str) if output_data is not None else None,
            error=error,
            duration_ms=duration_ms,
        )
        self._db.add(step)
        await self._db.commit()

    def finalize(
        self,
        *,
        status: str,
        final_action: str | None = None,
        journal_id: int | None = None,
        trade_id: int | None = None,
    ) -> None:
        """Set the final outcome — must be called before __aexit__."""
        self._final_status = status
        self._final_action = final_action
        self._journal_id = journal_id
        self._trade_id = trade_id

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._run and self._db:
            total_ms = int((time.monotonic() - self._start_ms) * 1000)
            self._run.status = "failed" if exc_type else self._final_status
            self._run.final_action = self._final_action
            self._run.total_duration_ms = total_ms
            self._run.journal_id = self._journal_id
            self._run.trade_id = self._trade_id
            await self._db.commit()

            run_id = self._run.id
            if not exc_type:
                try:
                    from api.routes.ws import broadcast
                    await broadcast(self._account_id, "pipeline_run_complete", {
                        "run_id": run_id,
                        "symbol": self._symbol,
                        "timeframe": self._timeframe,
                        "status": self._run.status,
                        "final_action": self._final_action,
                        "total_duration_ms": total_ms,
                        "step_count": self._seq,
                    })
                except Exception as exc:
                    logger.debug("WS broadcast failed (non-critical): %s", exc)

            logger.info(
                "PipelineTracer finished | run_id=%s status=%s action=%s duration_ms=%s",
                run_id, self._run.status, self._final_action, total_ms,
            )

        if self._session_ctx:
            await self._session_ctx.__aexit__(exc_type, exc_val, exc_tb)

        return False  # never suppress exceptions
```

**Step 2: Verify import works**

```bash
cd backend && uv run python -c "from services.pipeline_tracer import PipelineTracer; print('OK')"
```

Expected: `OK`

---

## Task 4: Change `analyze_market` to return prompt text and raw response

**Files:**

- Modify: `backend/ai/orchestrator.py`

**Step 1: Add `LLMAnalysisResult` dataclass and change return type**

Replace the current `analyze_market` function signature and body.

The key changes:

1. Add `from dataclasses import dataclass` to imports
2. Add `LLMAnalysisResult` dataclass after `TradingSignal`
3. Change `analyze_market` to capture the rendered prompt and raw response, then return `LLMAnalysisResult`

At the top of the file, add `from dataclasses import dataclass` to the imports block (after `from typing import Any`).

After the `TradingSignal` class definition, add:

```python
@dataclass
class LLMAnalysisResult:
    signal: TradingSignal
    prompt_text: str   # rendered human message sent to the LLM
    raw_response: dict[str, Any]  # raw dict from LLM before Pydantic parsing
```

In the `analyze_market` function:

- Change the return annotation from `-> TradingSignal:` to `-> LLMAnalysisResult:`
- After building `chart_section`, `positions_section`, etc., capture the rendered prompt:

```python
    prompt_vars = {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
        "indicators": json.dumps(indicators, indent=2),
        "ohlcv": json.dumps(ohlcv[-20:], indent=2, default=str),
        "chart_section": chart_section,
        "positions_section": positions_section,
        "signals_section": signals_section,
        "news_section": news_section,
        "history_section": history_section,
    }

    # Render the human message for capture (lightweight string format)
    prompt_text = _HUMAN.format(**prompt_vars)

    raw: dict = await chain.ainvoke(prompt_vars)
```

Replace the existing `raw: dict = await chain.ainvoke({...})` block with the above.

At the end, replace `return signal` with:

```python
    return LLMAnalysisResult(signal=signal, prompt_text=prompt_text, raw_response=raw)
```

**Step 2: Verify**

```bash
cd backend && uv run python -c "from ai.orchestrator import LLMAnalysisResult, analyze_market; print('OK')"
```

Expected: `OK`

---

## Task 5: Instrument `ai_trading.py` with `PipelineTracer`

**Files:**

- Modify: `backend/services/ai_trading.py`

**Step 1: Add imports at the top of `ai_trading.py`**

Add to the existing imports:

```python
import time
from services.pipeline_tracer import PipelineTracer
```

Change:

```python
from ai.orchestrator import TradingSignal, analyze_market
```

to:

```python
from ai.orchestrator import LLMAnalysisResult, TradingSignal, analyze_market
```

**Step 2: Wrap the full `analyze_and_trade` body with `PipelineTracer`**

The entire body of `analyze_and_trade` (from after the `db: AsyncSession` parameter) gets wrapped:

```python
    async def analyze_and_trade(self, account_id, symbol, timeframe, db, strategy_id=None, strategy_overrides=None):
        async with PipelineTracer(account_id, symbol, timeframe) as tracer:
            return await self._run_pipeline(tracer, account_id, symbol, timeframe, db, strategy_id, strategy_overrides)
```

Extract the existing body into a private `_run_pipeline` method and add `tracer` as its first parameter. Then instrument each step.

**Step 3: Full instrumented `_run_pipeline` method**

Replace the body of `analyze_and_trade` with this complete implementation (keep `analyze_and_trade` as a thin wrapper that creates the tracer):

```python
    async def analyze_and_trade(
        self,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None = None,
        strategy_overrides: "StrategyOverrides | None" = None,
    ) -> AnalysisResult:
        async with PipelineTracer(account_id, symbol, timeframe) as tracer:
            return await self._run_pipeline(
                tracer, account_id, symbol, timeframe, db, strategy_id, strategy_overrides
            )

    async def _run_pipeline(
        self,
        tracer: PipelineTracer,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None,
        strategy_overrides: "StrategyOverrides | None",
    ) -> AnalysisResult:
        """Full pipeline — called inside PipelineTracer context."""
        # 1. Load account
        t0 = time.monotonic()
        account: Account | None = await db.get(Account, account_id)
        if not account or not account.is_active:
            await tracer.record("account_loaded", status="error", error="Account not found or inactive",
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed")
            raise HTTPException(status_code=404, detail="Account not found")
        await tracer.record(
            "account_loaded",
            output_data={"name": account.name, "auto_trade_enabled": account.auto_trade_enabled,
                         "max_lot_size": account.max_lot_size},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # 2. Rate limit
        t0 = time.monotonic()
        allowed = await check_llm_rate_limit(account_id)
        if not allowed:
            await tracer.record("rate_limit_check", status="error",
                                output_data={"allowed": False},
                                error="LLM rate limit exceeded",
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed")
            logger.warning("LLM rate limit exceeded | account_id=%s", account_id)
            raise HTTPException(status_code=429,
                                detail="LLM rate limit exceeded — max 10 calls per 60 seconds per account")
        await tracer.record("rate_limit_check",
                            output_data={"allowed": True},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # 3. Resolve timeframe int
        tf_upper = timeframe.upper()
        tf_int = _TIMEFRAME_MAP.get(tf_upper)
        if tf_int is None:
            tracer.finalize(status="failed")
            raise HTTPException(status_code=422,
                                detail=f"Unknown timeframe '{timeframe}'. Supported: {list(_TIMEFRAME_MAP)}")

        # 4. Fetch / cache OHLCV
        t0 = time.monotonic()
        candles = await get_candle_cache(account_id, symbol, tf_upper)
        current_price: float | None = None
        ohlcv_source = "cache"

        if candles is None:
            ohlcv_source = "mt5"
            logger.info("OHLCV cache miss | account_id=%s symbol=%s tf=%s", account_id, symbol, tf_upper)
            password = decrypt(account.password_encrypted)
            creds = AccountCredentials(login=account.login, password=password,
                                       server=account.server, path=account.mt5_path or settings.mt5_path)
            try:
                async with MT5Bridge(creds) as bridge:
                    candles = await bridge.get_rates(symbol, tf_int, 50)
                    tick = await bridge.get_tick(symbol)
            except RuntimeError as exc:
                await tracer.record("ohlcv_fetch", status="error",
                                    input_data={"symbol": symbol, "timeframe": tf_upper},
                                    error=str(exc),
                                    duration_ms=int((time.monotonic() - t0) * 1000))
                tracer.finalize(status="failed")
                raise HTTPException(status_code=503, detail=str(exc))
            except ConnectionError as exc:
                await tracer.record("ohlcv_fetch", status="error",
                                    input_data={"symbol": symbol, "timeframe": tf_upper},
                                    error=str(exc),
                                    duration_ms=int((time.monotonic() - t0) * 1000))
                tracer.finalize(status="failed")
                raise HTTPException(status_code=502, detail=str(exc))

            if not candles:
                await tracer.record("ohlcv_fetch", status="error",
                                    input_data={"symbol": symbol, "timeframe": tf_upper},
                                    error="MT5 returned no candles",
                                    duration_ms=int((time.monotonic() - t0) * 1000))
                tracer.finalize(status="failed")
                raise HTTPException(status_code=502, detail=f"MT5 returned no candles for {symbol} {timeframe}")

            ttl = _CACHE_TTL.get(tf_upper, 60)
            await set_candle_cache(account_id, symbol, tf_upper, candles, ttl)

            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

        if current_price is None and candles:
            current_price = float(candles[-1].get("close", 0))

        await tracer.record(
            "ohlcv_fetch",
            input_data={"symbol": symbol, "timeframe": tf_upper},
            output_data={"source": ohlcv_source, "candle_count": len(candles or []),
                         "current_price": current_price},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # 5. Compute basic indicators
        t0 = time.monotonic()
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        indicators = {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }
        await tracer.record("indicators_computed",
                            output_data=indicators,
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # 6. Fetch position context and recent signals
        t0 = time.monotonic()
        open_positions: list[dict] = []
        try:
            pos_password = decrypt(account.password_encrypted)
            pos_creds = AccountCredentials(login=account.login, password=pos_password,
                                           server=account.server, path=account.mt5_path or settings.mt5_path)
            async with MT5Bridge(pos_creds) as pos_bridge:
                raw_positions = await pos_bridge.get_positions()
            open_positions = [
                {"symbol": p.get("symbol", ""), "direction": "BUY" if p.get("type") == 0 else "SELL",
                 "volume": p.get("volume", 0), "profit": p.get("profit", 0)}
                for p in raw_positions
            ]
        except Exception as exc:
            logger.warning("Could not fetch positions for LLM context | account_id=%s: %s", account_id, exc)
        await tracer.record("positions_fetched",
                            output_data={"positions": open_positions, "count": len(open_positions)},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        t0 = time.monotonic()
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
                {"symbol": j.symbol, "signal": j.signal, "confidence": j.confidence,
                 "rationale": j.rationale[:120]}
                for j in journal_rows
            ]
        except Exception as exc:
            logger.warning("Could not fetch recent signals | account_id=%s: %s", account_id, exc)
        await tracer.record("signals_fetched",
                            output_data={"signals": recent_signals, "count": len(recent_signals)},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        news_context_str: str | None = None
        if getattr(settings, "news_enabled", False):
            from services.market_context import fetch_upcoming_events, format_news_context
            events = await fetch_upcoming_events([symbol])
            news_context_str = format_news_context(events) or None

        trade_history_context: str | None = None
        try:
            hist_svc = HistoryService()
            recent_deals = await hist_svc.get_raw_deals(account, days=30)
            out_deals, in_by_pos = HistoryService._pair_deals(recent_deals)
            trade_history_context = HistoryService.format_for_llm(out_deals, in_by_pos, limit=10) or None
        except Exception as exc:
            logger.warning("Could not fetch trade history | account_id=%s: %s", account_id, exc)

        # 7. LLM analysis
        t0 = time.monotonic()
        llm_result = await analyze_market(
            symbol=symbol, timeframe=tf_upper, current_price=current_price or 0,
            indicators=indicators, ohlcv=candles,
            open_positions=open_positions, recent_signals=recent_signals,
            news_context=news_context_str, trade_history_context=trade_history_context,
            system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
        )
        signal = llm_result.signal
        await tracer.record(
            "llm_analyzed",
            input_data={"prompt": llm_result.prompt_text[:4000]},  # cap at 4000 chars
            output_data={"raw_response": llm_result.raw_response,
                         "provider": settings.llm_provider,
                         "action": signal.action, "confidence": signal.confidence},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # 8. Confidence gate
        action_before = signal.action
        if signal.confidence < settings.llm_confidence_threshold:
            logger.info("Signal downgraded to HOLD — confidence %.2f below threshold %.2f | symbol=%s",
                        signal.confidence, settings.llm_confidence_threshold, symbol)
            signal.action = "HOLD"
        await tracer.record(
            "confidence_gate",
            input_data={"confidence": signal.confidence, "threshold": settings.llm_confidence_threshold},
            output_data={"action_before": action_before, "action_after": signal.action},
        )

        logger.info("Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
                    symbol, signal.action, signal.confidence, signal.timeframe)

        # 9. Persist AIJournal
        t0 = time.monotonic()
        journal = AIJournal(
            account_id=account_id, trade_id=None, symbol=symbol, timeframe=tf_upper,
            signal=signal.action, confidence=signal.confidence, rationale=signal.rationale,
            indicators_snapshot=json.dumps(indicators),
            llm_provider=settings.llm_provider, model_name="", strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)
        await tracer.record("journal_saved",
                            output_data={"journal_id": journal.id},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # 10. Broadcast ai_signal
        await broadcast(account_id, "ai_signal", {
            "journal_id": journal.id, "symbol": symbol, "timeframe": tf_upper,
            "action": signal.action, "confidence": signal.confidence, "rationale": signal.rationale,
            "entry": signal.entry, "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
        })

        # 11. Skip checks
        if signal.action == "HOLD":
            await tracer.record("kill_switch_check", output_data={"active": False, "skipped": "HOLD signal"})
            logger.info("Signal HOLD — no order | account_id=%s symbol=%s", account_id, symbol)
            tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        ks_active = kill_switch_active()
        await tracer.record("kill_switch_check", output_data={"active": ks_active})
        if ks_active:
            logger.warning("Kill switch active — order skipped | account_id=%s symbol=%s", account_id, symbol)
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        if not account.auto_trade_enabled:
            logger.info("Auto-trade disabled — order skipped | account_id=%s", account_id)
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        # 12. Build order request
        effective_lot_size = (
            strategy_overrides.lot_size
            if strategy_overrides and strategy_overrides.lot_size is not None
            else account.max_lot_size
        )
        order_req = OrderRequest(
            symbol=symbol, direction=signal.action, volume=effective_lot_size,
            entry_price=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            comment="AI-Trade",
        )
        await tracer.record("order_built",
                            input_data={"symbol": symbol, "direction": signal.action,
                                        "volume": effective_lot_size, "entry": signal.entry,
                                        "sl": signal.stop_loss, "tp": signal.take_profit})

        # 13. Connect MT5 and execute
        t0 = time.monotonic()
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(login=account.login, password=password,
                                   server=account.server, path=account.mt5_path or settings.mt5_path)
        try:
            async with MT5Bridge(creds) as bridge:
                executor = MT5Executor(bridge)
                order_result = await executor.place_order(order_req, dry_run=account.paper_trade_enabled)
        except (RuntimeError, ConnectionError) as exc:
            logger.error("MT5 error during order execution | account_id=%s | %s", account_id, exc)
            await tracer.record("mt5_executed", status="error", error=str(exc),
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        if not order_result.success:
            logger.error("Order failed | account_id=%s symbol=%s error=%s",
                         account_id, symbol, order_result.error)
            await tracer.record("mt5_executed", status="error",
                                output_data={"success": False, "error": order_result.error},
                                duration_ms=int((time.monotonic() - t0) * 1000))
            await send_alert(f"*Order Failed*\nAccount: {account_id} | {signal.action} {symbol}\nError: {order_result.error}")
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        await tracer.record("mt5_executed",
                            output_data={"success": True, "ticket": order_result.ticket,
                                         "paper_trade": account.paper_trade_enabled},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # 14. Persist Trade row
        trade = Trade(
            account_id=account_id, ticket=order_result.ticket, symbol=symbol,
            direction=signal.action, volume=effective_lot_size,
            entry_price=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            opened_at=datetime.now(UTC), source="ai",
            is_paper_trade=account.paper_trade_enabled, strategy_id=strategy_id,
        )
        db.add(trade)
        await db.flush()
        journal.trade_id = trade.id
        await db.commit()
        await db.refresh(trade)

        # 15. Broadcast trade_opened
        await broadcast(account_id, "trade_opened", {
            "ticket": order_result.ticket, "symbol": symbol, "direction": signal.action,
            "volume": effective_lot_size, "entry_price": signal.entry,
            "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
        })

        # 16. Send Telegram alert
        t0 = time.monotonic()
        paper_tag = " _(paper)_" if account.paper_trade_enabled else ""
        alert_msg = (
            f"*Trade Placed{paper_tag}*\n"
            f"Account: {account_id} | {signal.action} {effective_lot_size} {symbol}\n"
            f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"Ticket: {order_result.ticket}"
        )
        await send_alert(alert_msg)
        await tracer.record("telegram_sent",
                            output_data={"sent": True, "preview": alert_msg[:100]},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        logger.info("Trade executed | account_id=%s symbol=%s direction=%s ticket=%s",
                    account_id, symbol, signal.action, order_result.ticket)

        tracer.finalize(status="completed", final_action=signal.action,
                        journal_id=journal.id, trade_id=trade.id)
        return AnalysisResult(signal=signal, order_placed=True, ticket=order_result.ticket, journal_id=journal.id)
```

**Step 3: Verify import**

```bash
cd backend && uv run python -c "from services.ai_trading import AITradingService; print('OK')"
```

Expected: `OK`

---

## Task 6: API routes for pipeline runs

**Files:**

- Create: `backend/api/routes/pipeline.py`
- Modify: `backend/main.py`

**Step 1: Create `backend/api/routes/pipeline.py`**

```python
"""Pipeline run log API — list and detail views for AI trading pipeline runs."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PipelineRun, PipelineStep
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class PipelineStepOut(BaseModel):
    id: int
    run_id: int
    seq: int
    step_name: str
    status: str
    input_json: str | None
    output_json: str | None
    error: str | None
    duration_ms: int

    model_config = {"from_attributes": True}


class PipelineRunSummary(BaseModel):
    id: int
    account_id: int
    symbol: str
    timeframe: str
    status: str
    final_action: str | None
    total_duration_ms: int | None
    journal_id: int | None
    trade_id: int | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_custom(cls, run: PipelineRun) -> "PipelineRunSummary":
        return cls(
            id=run.id,
            account_id=run.account_id,
            symbol=run.symbol,
            timeframe=run.timeframe,
            status=run.status,
            final_action=run.final_action,
            total_duration_ms=run.total_duration_ms,
            journal_id=run.journal_id,
            trade_id=run.trade_id,
            created_at=run.created_at.isoformat(),
        )


class PipelineRunDetail(BaseModel):
    run: PipelineRunSummary
    steps: list[PipelineStepOut]


@router.get("/runs", response_model=list[PipelineRunSummary])
async def list_runs(
    account_id: int | None = Query(None),
    symbol: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[PipelineRunSummary]:
    q = select(PipelineRun).order_by(desc(PipelineRun.created_at))
    if account_id is not None:
        q = q.where(PipelineRun.account_id == account_id)
    if symbol:
        q = q.where(PipelineRun.symbol == symbol)
    if status:
        q = q.where(PipelineRun.status == status)
    q = q.limit(limit).offset(offset)
    runs = (await db.execute(q)).scalars().all()
    return [PipelineRunSummary.from_orm_custom(r) for r in runs]


@router.get("/runs/{run_id}", response_model=PipelineRunDetail)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> PipelineRunDetail:
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    steps_q = (
        select(PipelineStep)
        .where(PipelineStep.run_id == run_id)
        .order_by(PipelineStep.seq)
    )
    steps = (await db.execute(steps_q)).scalars().all()
    return PipelineRunDetail(
        run=PipelineRunSummary.from_orm_custom(run),
        steps=[PipelineStepOut.model_validate(s) for s in steps],
    )
```

**Step 2: Register the router in `backend/main.py`**

In the imports section, add:

```python
from api.routes import pipeline as pipeline_routes
```

After the last `app.include_router(...)` line, add:

```python
app.include_router(pipeline_routes.router, prefix="/api/v1/pipeline", tags=["pipeline"])
```

**Step 3: Verify the server starts and routes appear**

```bash
cd backend && uv run python -c "
import asyncio
from main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
pipeline_routes = [r for r in routes if 'pipeline' in r]
print(pipeline_routes)
"
```

Expected: `['/api/v1/pipeline/runs', '/api/v1/pipeline/runs/{run_id}']`

---

## Task 7: Frontend types

**Files:**

- Modify: `frontend/src/types/trading.ts`

**Step 1: Add `PipelineStep`, `PipelineRunSummary`, `PipelineRunDetail` interfaces and update `WSEventType`**

At the end of `frontend/src/types/trading.ts`, append:

```typescript
// ── Pipeline Logs ─────────────────────────────────────────────────────────────

export interface PipelineStep {
  id: number;
  run_id: number;
  seq: number;
  step_name: string;
  status: "ok" | "skip" | "error";
  input_json: string | null;
  output_json: string | null;
  error: string | null;
  duration_ms: number;
}

export interface PipelineRunSummary {
  id: number;
  account_id: number;
  symbol: string;
  timeframe: string;
  status: "running" | "completed" | "hold" | "skipped" | "failed";
  final_action: "BUY" | "SELL" | "HOLD" | null;
  total_duration_ms: number | null;
  journal_id: number | null;
  trade_id: number | null;
  created_at: string;
}

export interface PipelineRunDetail {
  run: PipelineRunSummary;
  steps: PipelineStep[];
}

export interface PipelineRunCompleteData {
  run_id: number;
  symbol: string;
  timeframe: string;
  status: string;
  final_action: string | null;
  total_duration_ms: number;
  step_count: number;
}
```

Also update the `WSEventType` union to include the new event:

```typescript
export type WSEventType =
  | "equity_update"
  | "positions_update"
  | "trade_opened"
  | "trade_closed"
  | "ai_signal"
  | "kill_switch_triggered"
  | "pipeline_run_complete";
```

**Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors

---

## Task 8: Frontend API client

**Files:**

- Modify: `frontend/src/lib/api.ts`

**Step 1: Add `logsApi` to `frontend/src/lib/api.ts`**

Append at the end of the file:

```typescript
// ── Pipeline Logs ─────────────────────────────────────────────────────────────

export const logsApi = {
  listRuns: (params?: {
    account_id?: number;
    symbol?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null)
      query.set("account_id", String(params.account_id));
    if (params?.symbol) query.set("symbol", params.symbol);
    if (params?.status) query.set("status", params.status);
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").PipelineRunSummary[]>(
      `/pipeline/runs${qs ? `?${qs}` : ""}`,
    );
  },

  getRun: (runId: number) =>
    apiRequest<import("@/types/trading").PipelineRunDetail>(
      `/pipeline/runs/${runId}`,
    ),
};
```

**Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors

---

## Task 9: Frontend components

**Files:**

- Create: `frontend/src/components/logs/pipeline-step-card.tsx`
- Create: `frontend/src/components/logs/pipeline-run-detail.tsx`
- Create: `frontend/src/components/logs/pipeline-runs-list.tsx`

### 9a. `pipeline-step-card.tsx`

**Step 1: Create `frontend/src/components/logs/pipeline-step-card.tsx`**

```tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { PipelineStep } from "@/types/trading";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-green-500/15 text-green-700 dark:text-green-400",
  skip: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  error: "bg-red-500/15 text-red-700 dark:text-red-400",
};

const STEP_LABELS: Record<string, string> = {
  account_loaded: "Account Loaded",
  rate_limit_check: "Rate Limit Check",
  ohlcv_fetch: "OHLCV Fetch",
  indicators_computed: "Indicators Computed",
  positions_fetched: "Positions Fetched",
  signals_fetched: "Recent Signals Fetched",
  llm_analyzed: "LLM Analysis",
  confidence_gate: "Confidence Gate",
  journal_saved: "Journal Saved",
  kill_switch_check: "Kill Switch Check",
  order_built: "Order Built",
  mt5_executed: "MT5 Order Executed",
  telegram_sent: "Telegram Alert Sent",
};

interface PipelineStepCardProps {
  step: PipelineStep;
}

function JsonViewer({ raw }: { raw: string | null }) {
  if (!raw) return <span className="text-muted-foreground text-xs">—</span>;
  try {
    const parsed = JSON.parse(raw);
    return (
      <pre className="text-xs bg-muted/50 rounded p-2 overflow-auto max-h-48 whitespace-pre-wrap break-all">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    );
  } catch {
    return <pre className="text-xs text-muted-foreground">{raw}</pre>;
  }
}

export function PipelineStepCard({ step }: PipelineStepCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = step.input_json || step.output_json || step.error;
  const label = STEP_LABELS[step.step_name] ?? step.step_name;

  return (
    <div className="border-l-2 border-muted pl-4 py-1">
      <button
        className="flex items-center gap-2 w-full text-left group"
        onClick={() => hasDetail && setExpanded((v) => !v)}
        disabled={!hasDetail}
      >
        <span className="text-muted-foreground text-xs w-4 shrink-0">
          {step.seq}.
        </span>
        <span className="flex-1 text-sm font-medium">{label}</span>
        <Badge
          className={`text-xs shrink-0 ${STATUS_STYLES[step.status] ?? ""}`}
          variant="outline"
        >
          {step.status}
        </Badge>
        <span className="text-xs text-muted-foreground w-16 text-right shrink-0">
          {step.duration_ms}ms
        </span>
        {hasDetail && (
          <span className="text-muted-foreground shrink-0">
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </span>
        )}
      </button>

      {expanded && hasDetail && (
        <div className="mt-2 space-y-2">
          {step.error && (
            <div>
              <p className="text-xs font-semibold text-red-600 mb-1">Error</p>
              <pre className="text-xs bg-red-50 dark:bg-red-950/20 rounded p-2 text-red-700 dark:text-red-400 whitespace-pre-wrap">
                {step.error}
              </pre>
            </div>
          )}
          {step.input_json && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">
                Input
              </p>
              <JsonViewer raw={step.input_json} />
            </div>
          )}
          {step.output_json && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">
                Output
              </p>
              <JsonViewer raw={step.output_json} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

### 9b. `pipeline-run-detail.tsx`

**Step 2: Create `frontend/src/components/logs/pipeline-run-detail.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineStepCard } from "./pipeline-step-card";
import { logsApi } from "@/lib/api";
import type { PipelineRunDetail, PipelineRunSummary } from "@/types/trading";

const STATUS_VARIANT: Record<string, string> = {
  completed: "bg-green-500/15 text-green-700 dark:text-green-400",
  hold: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  skipped: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-400 animate-pulse",
};

const ACTION_VARIANT: Record<string, string> = {
  BUY: "bg-green-500/15 text-green-700 dark:text-green-400",
  SELL: "bg-red-500/15 text-red-700 dark:text-red-400",
  HOLD: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
};

interface PipelineRunDetailPanelProps {
  run: PipelineRunSummary;
}

export function PipelineRunDetailPanel({ run }: PipelineRunDetailPanelProps) {
  const [detail, setDetail] = useState<PipelineRunDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    logsApi
      .getRun(run.id)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [run.id]);

  const ts = new Date(run.created_at).toLocaleString();

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-sm">
            Run #{run.id} — {run.symbol} {run.timeframe}
          </span>
          <Badge
            variant="outline"
            className={`text-xs ${STATUS_VARIANT[run.status] ?? ""}`}
          >
            {run.status}
          </Badge>
          {run.final_action && (
            <Badge
              variant="outline"
              className={`text-xs ${ACTION_VARIANT[run.final_action] ?? ""}`}
            >
              {run.final_action}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {ts}
          {run.total_duration_ms != null &&
            ` · ${run.total_duration_ms}ms total`}
          {run.trade_id && ` · Trade #${run.trade_id}`}
        </p>
      </div>

      {/* Steps */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {loading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))
        ) : detail ? (
          detail.steps.map((step) => (
            <PipelineStepCard key={step.id} step={step} />
          ))
        ) : (
          <p className="text-sm text-muted-foreground">Failed to load steps.</p>
        )}
      </div>
    </div>
  );
}
```

### 9c. `pipeline-runs-list.tsx`

**Step 3: Create `frontend/src/components/logs/pipeline-runs-list.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { logsApi } from "@/lib/api";
import { useTradingStore } from "@/hooks/use-trading-store";
import type {
  PipelineRunCompleteData,
  PipelineRunSummary,
} from "@/types/trading";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-green-500/15 text-green-700 dark:text-green-400",
  hold: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  skipped: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400",
  running: "bg-blue-500/15 text-blue-600 dark:text-blue-400 animate-pulse",
};

const ACTION_DOT: Record<string, string> = {
  BUY: "bg-green-500",
  SELL: "bg-red-500",
  HOLD: "bg-yellow-500",
};

function timeAgo(isoString: string): string {
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(isoString).toLocaleDateString();
}

interface PipelineRunsListProps {
  selectedRunId: number | null;
  onSelect: (run: PipelineRunSummary) => void;
  onNewRun?: (data: PipelineRunCompleteData) => void;
}

export function PipelineRunsList({
  selectedRunId,
  onSelect,
  onNewRun,
}: PipelineRunsListProps) {
  const { activeAccountId } = useTradingStore();
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const newRunIdsRef = useRef<Set<number>>(new Set());

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await logsApi.listRuns({
        account_id: activeAccountId ?? undefined,
        symbol: symbolFilter.trim().toUpperCase() || undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        limit: 100,
      });
      setRuns(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [activeAccountId, symbolFilter, statusFilter]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Accept new run notifications from parent (via WebSocket)
  useEffect(() => {
    if (!onNewRun) return;
    // parent passes run summaries via onNewRun — handled in page.tsx
  }, [onNewRun]);

  const handleNewRun = useCallback(
    (data: PipelineRunCompleteData) => {
      const newSummary: PipelineRunSummary = {
        id: data.run_id,
        account_id: activeAccountId ?? 0,
        symbol: data.symbol,
        timeframe: data.timeframe,
        status: data.status as PipelineRunSummary["status"],
        final_action: data.final_action as PipelineRunSummary["final_action"],
        total_duration_ms: data.total_duration_ms,
        journal_id: null,
        trade_id: null,
        created_at: new Date().toISOString(),
      };
      newRunIdsRef.current.add(data.run_id);
      setRuns((prev) => [newSummary, ...prev.slice(0, 99)]);
      setTimeout(() => {
        newRunIdsRef.current.delete(data.run_id);
      }, 3000);
    },
    [activeAccountId],
  );

  // Expose handleNewRun to parent
  useEffect(() => {
    if (onNewRun) {
      // This pattern lets the page wire WS → list
      (onNewRun as unknown as { _handler?: typeof handleNewRun })._handler =
        handleNewRun;
    }
  }, [onNewRun, handleNewRun]);

  return (
    <div className="h-full flex flex-col">
      {/* Filters */}
      <div className="p-3 border-b space-y-2">
        <Input
          placeholder="Symbol filter (e.g. EURUSD)"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="h-8 text-sm"
        />
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="hold">Hold</SelectItem>
            <SelectItem value="skipped">Skipped</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto divide-y">
        {loading ? (
          Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="p-3">
              <Skeleton className="h-4 w-3/4 mb-1" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))
        ) : runs.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No runs found.</p>
        ) : (
          runs.map((run) => {
            const isNew = newRunIdsRef.current.has(run.id);
            const isSelected = run.id === selectedRunId;
            return (
              <button
                key={run.id}
                onClick={() => onSelect(run)}
                className={[
                  "w-full text-left px-3 py-2.5 transition-colors",
                  isSelected ? "bg-accent" : "hover:bg-accent/50",
                  isNew ? "animate-pulse bg-primary/5" : "",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  {run.final_action && (
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${ACTION_DOT[run.final_action] ?? "bg-muted"}`}
                    />
                  )}
                  <span className="text-sm font-medium flex-1 truncate">
                    {run.symbol} {run.timeframe}
                  </span>
                  <Badge
                    variant="outline"
                    className={`text-xs shrink-0 ${STATUS_STYLES[run.status] ?? ""}`}
                  >
                    {run.status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 pl-4">
                  #{run.id} · {timeAgo(run.created_at)}
                  {run.total_duration_ms != null &&
                    ` · ${run.total_duration_ms}ms`}
                </p>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
```

---

## Task 10: Frontend page and sidebar

**Files:**

- Create: `frontend/src/app/logs/page.tsx`
- Modify: `frontend/src/components/app-sidebar.tsx`

### 10a. Page

**Step 1: Create `frontend/src/app/logs/page.tsx`**

```tsx
"use client";

import { useCallback, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/use-websocket";
import { useTradingStore } from "@/hooks/use-trading-store";
import { PipelineRunsList } from "@/components/logs/pipeline-runs-list";
import { PipelineRunDetailPanel } from "@/components/logs/pipeline-run-detail";
import type {
  PipelineRunCompleteData,
  PipelineRunSummary,
} from "@/types/trading";

export default function LogsPage() {
  const { activeAccountId } = useTradingStore();
  const [selectedRun, setSelectedRun] = useState<PipelineRunSummary | null>(
    null,
  );
  const handleNewRunRef = useRef<
    ((data: PipelineRunCompleteData) => void) | null
  >(null);

  const handleNewRun = useCallback((data: PipelineRunCompleteData) => {
    handleNewRunRef.current?.(data);
  }, []);

  useWebSocket(activeAccountId, {
    pipeline_run_complete: (data) => {
      handleNewRun(data as PipelineRunCompleteData);
    },
  });

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Left — runs list */}
      <div className="w-72 shrink-0 border-r flex flex-col">
        <div className="p-3 border-b">
          <h2 className="font-semibold text-sm">Pipeline Logs</h2>
          <p className="text-xs text-muted-foreground">
            Every AI analysis run, step by step
          </p>
        </div>
        <PipelineRunsList
          selectedRunId={selectedRun?.id ?? null}
          onSelect={setSelectedRun}
          onNewRun={(fn) => {
            handleNewRunRef.current = fn as unknown as (
              data: PipelineRunCompleteData,
            ) => void;
          }}
        />
      </div>

      {/* Right — detail */}
      <div className="flex-1 overflow-hidden">
        {selectedRun ? (
          <PipelineRunDetailPanel run={selectedRun} />
        ) : (
          <div className="h-full flex items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Select a run from the list to see its step trace.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
```

### 10b. Sidebar

**Step 2: Add "Pipeline Logs" to `frontend/src/components/app-sidebar.tsx`**

Add `ScrollText` to the lucide-react import:

```tsx
import {
  BarChart3,
  Brain,
  Cpu,
  LayoutDashboard,
  ScrollText,
  Settings,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";
```

Add to the `navItems` array (after `"AI Signals"`):

```tsx
  { title: "Pipeline Logs", url: "/logs", icon: ScrollText },
```

**Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors

**Step 4: Start dev server and verify the page loads**

```bash
cd frontend && npm run dev
```

Navigate to `http://localhost:3000/logs`. Expected: two-panel layout renders, left panel shows filters and empty state or a loading skeleton, no console errors.

---

## Task 11: End-to-end smoke test

**Step 1: Start backend**

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

**Step 2: Trigger an AI analysis via the API**

```bash
curl -X POST http://localhost:8000/api/v1/accounts/1/analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol": "EURUSD", "timeframe": "M15"}'
```

**Step 3: Check that a pipeline run was created**

```bash
curl http://localhost:8000/api/v1/pipeline/runs?limit=1
```

Expected: JSON array with one run object containing `id`, `status`, `symbol`, etc.

**Step 4: Check that steps were created**

```bash
curl http://localhost:8000/api/v1/pipeline/runs/1
```

Expected: `{"run": {...}, "steps": [{seq:1, step_name:"account_loaded", ...}, ...]}` with 8–13 steps.

**Step 5: Open the dashboard and verify live update**

- Open `http://localhost:3000/logs` (connected to WebSocket)
- Trigger another analysis
- Verify: a new row appears at the top of the left panel
- Click it: verify steps appear in the right panel with durations and expandable JSON
