# AI Trading Service Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `backend/services/ai_trading.py` (1272 lines, one god-method) into a focused package with no behavior changes.

**Architecture:** Convert `services/ai_trading.py` → `services/ai_trading/` package. Each sub-module owns one pipeline concern. External callers continue importing `from services.ai_trading import AITradingService, AnalysisResult` unchanged via `__init__.py`. The `_run_pipeline` method becomes a ~120-line orchestrator that delegates to private helpers.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, LangChain, MetaTrader5 bridge.

---

## File Map

| File | Lines (target) | Responsibility |
|---|---|---|
| `services/ai_trading/__init__.py` | ~10 | Re-exports — public API surface unchanged |
| `services/ai_trading/_models.py` | ~45 | `StrategyOverrides`, `AnalysisResult`, `SharedMarketContext` dataclasses |
| `services/ai_trading/_helpers.py` | ~110 | Constants, pure functions, `record_llm_role` helper |
| `services/ai_trading/_market_data.py` | ~170 | OHLCV fetch, market open check, indicator computation, context-TF candles |
| `services/ai_trading/_context.py` | ~130 | Positions, recent signals, news context, trade history + RAG |
| `services/ai_trading/_signal.py` | ~220 | Risk pre-check, rule-based path, LLM analysis path, news filter gate |
| `services/ai_trading/_execution.py` | ~180 | Lot size, `OrderRequest` build, MT5 execute, `Trade` + `AIJournal` persist |
| `services/ai_trading/_service.py` | ~140 | `AITradingService` — thin orchestrator only |
| `services/ai_trading.py` | **deleted** | Replaced by package |

**Zero changes to:**
- `backend/api/routes/scheduler.py`
- `backend/services/scheduler.py`
- Any file importing `from services.ai_trading import ...`
- Test files (all existing tests must pass throughout)

---

## Task 1: Create package skeleton and extract `_models.py`

**Files:**
- Create: `backend/services/ai_trading/__init__.py`
- Create: `backend/services/ai_trading/_models.py`

The dataclasses live at lines 151–187 of the original file. Move them verbatim; add a forward reference fix for `SharedMarketContext` in `AnalysisResult`.

- [ ] **Step 1: Create the package directory**

```bash
mkdir backend/services/ai_trading
```

- [ ] **Step 2: Create `_models.py`**

```python
# backend/services/ai_trading/_models.py
"""Domain dataclasses for the AI trading pipeline."""
from __future__ import annotations

from dataclasses import dataclass

from ai.orchestrator import LLMAnalysisResult, TradingSignal


@dataclass
class StrategyOverrides:
    """Per-strategy execution overrides passed from the scheduler."""
    lot_size: float | None = None
    custom_prompt: str | None = None
    news_filter: bool = False


@dataclass
class SharedMarketContext:
    """Market analysis result shared across accounts in a group job.

    The primary account runs the full LLM pipeline and stores results here;
    secondary accounts skip OHLCV fetch and LLM and reuse this context.
    """
    symbol: str
    mt5_symbol: str
    timeframe: str
    candles: list[dict]
    indicators: dict
    current_price: float
    signal: TradingSignal
    llm_result: LLMAnalysisResult | None = None
    news_signal: str | None = None


@dataclass
class AnalysisResult:
    """Return value of AITradingService.analyze_and_trade."""
    signal: TradingSignal
    order_placed: bool
    ticket: int | None
    journal_id: int
    shared_ctx: SharedMarketContext | None = None
```

- [ ] **Step 3: Create a minimal `__init__.py` that re-exports everything callers currently import**

```python
# backend/services/ai_trading/__init__.py
"""AI Trading Service package.

Public surface — matches the old services/ai_trading.py module exactly.
"""
from services.ai_trading._models import AnalysisResult, SharedMarketContext, StrategyOverrides
from services.ai_trading._service import AITradingService

__all__ = [
    "AITradingService",
    "AnalysisResult",
    "SharedMarketContext",
    "StrategyOverrides",
]
```

> `_service.py` does not exist yet — this will fail to import until Task 7. That is expected. Do NOT run the full test suite yet.

- [ ] **Step 4: Verify the models parse cleanly**

```bash
cd backend && uv run python -c "from services.ai_trading._models import AnalysisResult, SharedMarketContext, StrategyOverrides; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_trading/__init__.py backend/services/ai_trading/_models.py
git commit -m "refactor(ai-trading): create package skeleton and extract _models"
```

---

## Task 2: Extract `_helpers.py`

**Files:**
- Create: `backend/services/ai_trading/_helpers.py`

Move from the original file:
- Lines 53–57: `_TIMEFRAME_MAP`
- Lines 59–63: `_CACHE_TTL`
- Lines 65–66: `_MT5_MIN_LOT`
- Lines 69–95: `_calculate_lot_size()`
- Lines 97–108: `_provider_name()`
- Lines 109–139: `_get_task_llm()`
- Lines 141–149: `_news_direction()`
- Lines 823–872 (nested in `_run_pipeline`): `_record_llm_role()` — extracted to a free async function with `tracer` as an explicit parameter.

- [ ] **Step 1: Create `_helpers.py`**

```python
# backend/services/ai_trading/_helpers.py
"""Constants and pure/utility functions shared across the AI trading pipeline."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import LLMRoleResult
from core.llm_pricing import compute_cost

if TYPE_CHECKING:
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)

# ── MT5 timeframe integer constants ──────────────────────────────────────────
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

# ── OHLCV cache TTL by timeframe (seconds) ───────────────────────────────────
_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}

_MT5_MIN_LOT = 0.01


def _calculate_lot_size(
    balance: float,
    risk_pct: float,
    sl_pips: float,
    pip_value_per_lot: float,
    max_lot: float,
    min_lot: float = _MT5_MIN_LOT,
) -> float:
    """Compute risk-proportional lot size, clamped to [min_lot, max_lot].

    Formula: lot = (balance * risk_pct) / (sl_pips * pip_value_per_lot)
    """
    if sl_pips <= 0 or pip_value_per_lot <= 0:
        return min_lot
    raw = (balance * risk_pct) / (sl_pips * pip_value_per_lot)
    return round(max(min_lot, min(raw, max_lot)), 2)


def _provider_name(provider: str | None) -> str:
    """Normalise LLM provider name for display."""
    mapping = {"openai": "OpenAI", "gemini": "Google Gemini", "anthropic": "Anthropic"}
    return mapping.get((provider or "").lower(), provider or "unknown")


async def _get_task_llm(task: str, db: AsyncSession) -> object | None:
    """Return the configured LLM instance for a named pipeline task, or None.

    Looks up TaskLLMConfig rows; returns None if no override is configured so
    the orchestrator falls back to the global default.
    """
    from db.models import TaskLLMConfig  # local import avoids circular dep
    from ai.orchestrator import build_llm  # local import — heavy dep

    try:
        row = (
            await db.execute(
                select(TaskLLMConfig).where(TaskLLMConfig.task_name == task)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return build_llm(provider=row.provider, model=row.model)
    except Exception as exc:
        logger.warning("Could not load task LLM config for '%s': %s", task, exc)
        return None


def _news_direction(action: str) -> str:
    """Map a trading signal action to a news-compatible direction string."""
    action_upper = action.upper()
    if "BUY" in action_upper:
        return "BUY"
    if "SELL" in action_upper:
        return "SELL"
    return "HOLD"


async def record_llm_role(
    tracer: "PipelineTracer",
    role_result: LLMRoleResult,
    step_name: str,
    role: str,
    input_summary: dict,
) -> None:
    """Record a single LLM role's token usage to pipeline_steps + llm_calls tables."""
    input_payload: dict = input_summary
    if getattr(role_result, "prompt", None):
        input_payload = {"summary": input_summary, "prompt": role_result.prompt}

    step_id = await tracer.record(
        step_name,
        input_data=input_payload,
        output_data={
            "model": role_result.model,
            "provider": role_result.provider,
            "input_tokens": role_result.input_tokens,
            "output_tokens": role_result.output_tokens,
            "total_tokens": role_result.total_tokens,
            "content": (
                role_result.content
                if isinstance(role_result.content, dict)
                else str(role_result.content)[:500]
            ),
        },
        duration_ms=role_result.duration_ms,
    )
    cost = (
        compute_cost(
            role_result.model,
            role_result.input_tokens or 0,
            role_result.output_tokens or 0,
        )
        if role_result.input_tokens is not None
        else None
    )
    await tracer.record_llm_call(
        role=role,
        provider=role_result.provider,
        model=role_result.model,
        input_tokens=role_result.input_tokens,
        output_tokens=role_result.output_tokens,
        total_tokens=role_result.total_tokens,
        cost_usd=cost,
        duration_ms=role_result.duration_ms,
        pipeline_step_id=step_id,
    )
```

> Note: `_calculate_lot_size` body is at original lines 69–95. `_provider_name` at 97–108. `_get_task_llm` at 109–139. `_news_direction` at 141–149. `record_llm_role` body is the nested function at original lines 823–872 with `tracer` added as explicit first parameter (previously from closure).

- [ ] **Step 2: Verify it parses**

```bash
cd backend && uv run python -c "from services.ai_trading._helpers import _calculate_lot_size, _get_task_llm, record_llm_role; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_trading/_helpers.py
git commit -m "refactor(ai-trading): extract _helpers (constants, pure functions, record_llm_role)"
```

---

## Task 3: Extract `_market_data.py`

**Files:**
- Create: `backend/services/ai_trading/_market_data.py`

Extracts from `_run_pipeline`:
- Lines 312–435 (steps 4a–4c): timeframe resolve, MT5 bridge, market open check, OHLCV fetch + cache
- Lines 437–514 (step 5): indicator computation via pandas-ta
- Lines 743–777 (step 8, context TF fetch): context timeframe OHLCV fetch

- [ ] **Step 1: Create `_market_data.py`**

```python
# backend/services/ai_trading/_market_data.py
"""OHLCV data fetching, caching, and indicator computation."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ai.vision import generate_ohlcv_chart
from core.config import settings
from core.security import decrypt
from db.redis import get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from services.ai_trading._helpers import _CACHE_TTL, _TIMEFRAME_MAP

if TYPE_CHECKING:
    from db.models import Account
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)


def resolve_timeframe(timeframe: str) -> tuple[str, int]:
    """Return (tf_upper, tf_int) or raise HTTPException 422 on unknown value."""
    tf_upper = timeframe.upper()
    tf_int = _TIMEFRAME_MAP.get(tf_upper)
    if tf_int is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown timeframe '{timeframe}'. Supported: {list(_TIMEFRAME_MAP)}",
        )
    return tf_upper, tf_int


async def fetch_ohlcv(
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    tf_int: int,
    tracer: "PipelineTracer",
) -> tuple[list[dict], str, float | None]:
    """Fetch OHLCV candles (Redis cache → MT5 on miss). Also checks market open.

    Returns:
        (candles, mt5_symbol, current_price)

    Raises:
        HTTPException 503 — market closed, or MT5 runtime/connection error
        HTTPException 502 — MT5 returned no candles
    """
    t0 = time.monotonic()
    candles = await get_candle_cache(account_id, symbol, tf_upper)
    current_price: float | None = None
    ohlcv_source = "cache"
    mt5_symbol: str = symbol

    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login,
        password=password,
        server=account.server,
        path=account.mt5_path or settings.mt5_path,
    )

    try:
        async with MT5Bridge(creds) as bridge:
            mt5_symbol = await bridge.get_broker_symbol(symbol)

            t_market = time.monotonic()
            is_open, trade_mode_name = await bridge.is_market_open(mt5_symbol)
            await tracer.record(
                "market_open_check",
                output_data={"trade_mode": trade_mode_name, "is_open": is_open},
                status="ok" if is_open else "skipped",
                duration_ms=int((time.monotonic() - t_market) * 1000),
            )
            if not is_open:
                logger.info(
                    "Market closed (%s) — skipping LLM pipeline | account_id=%s symbol=%s",
                    trade_mode_name, account_id, mt5_symbol,
                )
                tracer.finalize(status="skipped")
                raise HTTPException(
                    status_code=503,
                    detail=f"Market is closed for {symbol} (trade_mode={trade_mode_name})",
                )

            if candles is None:
                ohlcv_source = "mt5"
                logger.info(
                    "OHLCV cache miss | account_id=%s symbol=%s tf=%s",
                    account_id, symbol, tf_upper,
                )
                tick = None
                for _attempt in range(2):
                    candles = await bridge.get_rates(mt5_symbol, tf_int, 250)
                    if candles:
                        break
                    if _attempt == 0:
                        logger.warning(
                            "MT5 returned no candles (attempt 1) — retrying in 1s | symbol=%s tf=%s",
                            mt5_symbol, tf_upper,
                        )
                        await asyncio.sleep(1)
                tick = await bridge.get_tick(mt5_symbol)
                if tick:
                    current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

    except HTTPException:
        raise
    except RuntimeError as exc:
        await tracer.record(
            "ohlcv_fetch", status="error",
            input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed")
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        await tracer.record(
            "ohlcv_fetch", status="error",
            input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed")
        raise HTTPException(status_code=502, detail=str(exc))

    if ohlcv_source == "mt5":
        if not candles:
            await tracer.record(
                "ohlcv_fetch", status="error",
                input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
                error="MT5 returned no candles",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            tracer.finalize(status="failed")
            raise HTTPException(
                status_code=502,
                detail=f"MT5 returned no candles for {mt5_symbol} {tf_upper}",
            )
        ttl = _CACHE_TTL.get(tf_upper, 60)
        await set_candle_cache(account_id, symbol, tf_upper, candles, ttl)

    if current_price is None and candles:
        current_price = float(candles[-1].get("close", 0))

    await tracer.record(
        "ohlcv_fetch",
        input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
        output_data={
            "source": ohlcv_source,
            "candle_count": len(candles or []),
            "current_price": current_price,
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return candles, mt5_symbol, current_price


def compute_indicators(candles: list[dict]) -> dict:
    """Compute pandas-ta indicators from OHLCV candles.

    Falls back to basic SMA/high/low if pandas-ta is not installed or
    there are fewer than 200 candles. NaN values are replaced with 0.0.
    """
    def _basic(candles: list[dict]) -> dict:
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        return {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }

    try:
        import pandas as pd
        import pandas_ta as ta  # noqa: F401

        df = pd.DataFrame(candles)
        if df.empty or len(df) < 200:
            logger.warning("Insufficient candles for pandas-ta (need >= 200). Using basic.")
            return _basic(candles)

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
        result = {
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
    except ImportError:
        logger.warning("pandas or pandas-ta not installed. Falling back to basic indicators.")
        result = _basic(candles)
    except Exception as exc:
        logger.exception("Error computing advanced indicators: %s", exc)
        result = _basic(candles)

    # Replace NaN (pandas artifact) with 0.0 — json.dumps fails on NaN
    return {k: (0.0 if isinstance(v, float) and math.isnan(v) else v) for k, v in result.items()}


async def fetch_context_ohlcv(
    account: "Account",
    account_id: int,
    symbol: str,
    primary_tf: str,
    strategy_id: int | None,
    db: AsyncSession,
) -> dict[str, list[dict]]:
    """Fetch OHLCV for context timeframes defined on the strategy.

    Returns a mapping of {tf_upper: candles}. Empty dict if strategy has no
    context_tfs or strategy_id is None.
    """
    if not strategy_id:
        return {}

    from db.models import Strategy  # local import avoids circular dep

    strat = await db.get(Strategy, strategy_id)
    if not strat or not strat.context_tfs or strat.context_tfs == "[]":
        return {}

    try:
        ctx_tfs: list[str] = json.loads(strat.context_tfs)
    except json.JSONDecodeError:
        return {}

    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login,
        password=password,
        server=account.server,
        path=account.mt5_path or settings.mt5_path,
    )

    context_ohlcv: dict[str, list[dict]] = {}
    for ctx_tf in ctx_tfs:
        ctx_tf_upper = ctx_tf.upper()
        if ctx_tf_upper == primary_tf:
            continue
        ctx_candles = await get_candle_cache(account_id, symbol, ctx_tf_upper)
        if ctx_candles is None:
            ctx_tf_int = _TIMEFRAME_MAP.get(ctx_tf_upper)
            if ctx_tf_int is None:
                continue
            try:
                async with MT5Bridge(creds) as bridge:
                    mt5_sym = await bridge.get_broker_symbol(symbol)
                    ctx_candles = await bridge.get_rates(mt5_sym, ctx_tf_int, 20)
            except Exception as exc:
                logger.warning(
                    "Context TF fetch failed | symbol=%s tf=%s: %s",
                    symbol, ctx_tf_upper, exc,
                )
                ctx_candles = []
            if ctx_candles:
                ttl = _CACHE_TTL.get(ctx_tf_upper, 60)
                await set_candle_cache(account_id, symbol, ctx_tf_upper, ctx_candles, ttl)
        if ctx_candles:
            context_ohlcv[ctx_tf_upper] = ctx_candles

    return context_ohlcv


def maybe_chart(candles: list[dict], symbol: str, tf_upper: str) -> str | None:
    """Generate base64 OHLCV chart if chart vision is enabled in settings."""
    if not settings.enable_chart_vision:
        return None
    return generate_ohlcv_chart(candles, symbol, tf_upper)
```

- [ ] **Step 2: Verify it parses**

```bash
cd backend && uv run python -c "from services.ai_trading._market_data import fetch_ohlcv, compute_indicators, fetch_context_ohlcv; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_trading/_market_data.py
git commit -m "refactor(ai-trading): extract _market_data (OHLCV fetch, indicators, context TFs)"
```

---

## Task 4: Extract `_context.py`

**Files:**
- Create: `backend/services/ai_trading/_context.py`

Extracts from `_run_pipeline`:
- Lines 516–544 (step 6a): position context fetch
- Lines 546–574 (step 6b): recent signals fetch
- Lines 647–677 (step 8, LLM path): news context + trade history + RAG context

- [ ] **Step 1: Create `_context.py`**

```python
# backend/services/ai_trading/_context.py
"""Pipeline context fetchers: positions, signals, news, trade history, RAG."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import AIJournal
from mt5.bridge import AccountCredentials, MT5Bridge
from services.history_sync import HistoryService

if TYPE_CHECKING:
    from db.models import Account
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)


async def fetch_open_positions(
    account: "Account",
    account_id: int,
    tracer: "PipelineTracer",
) -> list[dict]:
    """Fetch open MT5 positions for the account; returns [] on error."""
    t0 = time.monotonic()
    open_positions: list[dict] = []
    try:
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            raw = await bridge.get_positions()
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
        logger.warning(
            "Could not fetch positions for LLM context | account_id=%s: %s",
            account_id, exc,
        )
    await tracer.record(
        "positions_fetched",
        output_data={"positions": open_positions, "count": len(open_positions)},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return open_positions


async def fetch_recent_signals(
    account_id: int,
    symbol: str,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> list[dict]:
    """Return the 5 most recent AIJournal entries for this account+symbol."""
    t0 = time.monotonic()
    recent_signals: list[dict] = []
    try:
        rows = (
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
            for j in rows
        ]
    except Exception as exc:
        logger.warning(
            "Could not fetch recent signals for LLM context | account_id=%s: %s",
            account_id, exc,
        )
    await tracer.record(
        "signals_fetched",
        output_data={"signals": recent_signals, "count": len(recent_signals)},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return recent_signals


async def build_trade_history_context(
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> str | None:
    """Assemble trade history + RAG self-calibration context string for the LLM.

    Returns None if both sources are empty.
    """
    trade_history_context: str | None = None

    # --- MT5 trade history (last 30 days) ---
    try:
        hist_svc = HistoryService()
        recent_deals = await hist_svc.get_raw_deals(account, days=30)
        out_deals, in_by_pos = HistoryService._pair_deals(recent_deals)
        trade_history_context = HistoryService.format_for_llm(out_deals, in_by_pos, limit=10) or None
    except Exception as exc:
        logger.warning(
            "Could not fetch trade history for LLM context | account_id=%s: %s",
            account_id, exc,
        )

    # --- RAG performance context ---
    from services.rag_context import build_rag_context  # heavy dep; lazy import

    rag_ctx = await build_rag_context(db, account_id, symbol, tf_upper)
    await tracer.record(
        "rag_context",
        output_data={"has_context": rag_ctx is not None, "length": len(rag_ctx) if rag_ctx else 0},
    )
    if rag_ctx:
        trade_history_context = (
            (trade_history_context + "\n\n" if trade_history_context else "") + rag_ctx
        )

    return trade_history_context


async def fetch_news_context(symbol: str) -> str | None:
    """Fetch upcoming calendar events and format as news context string.

    Returns None if news is disabled in settings or no events were found.
    """
    if not getattr(settings, "news_enabled", False):
        return None
    from services.market_context import fetch_upcoming_events, format_news_context  # lazy import

    events = await fetch_upcoming_events([symbol])
    return format_news_context(events) or None
```

- [ ] **Step 2: Verify it parses**

```bash
cd backend && uv run python -c "from services.ai_trading._context import fetch_open_positions, fetch_recent_signals, build_trade_history_context; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_trading/_context.py
git commit -m "refactor(ai-trading): extract _context (positions, signals, news, trade history, RAG)"
```

---

## Task 5: Extract `_signal.py`

**Files:**
- Create: `backend/services/ai_trading/_signal.py`

Extracts from `_run_pipeline`:
- Lines 576–609 (step 6.5): risk limit pre-check
- Lines 611–642 (step 7): rule-based signal
- Lines 645–918 (step 8): LLM analysis path (news gate, LLM calls, news filter, record roles, build SharedMarketContext)

This is the most complex extraction. The fast-path (shared_ctx) and full-path converge here. A `SignalPhaseResult` dataclass carries the outputs forward to the rest of the pipeline.

- [ ] **Step 1: Create `_signal.py`**

```python
# backend/services/ai_trading/_signal.py
"""Signal generation: risk pre-check, rule-based path, and LLM analysis path."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import LLMAnalysisResult, TradingSignal, analyze_market, analyze_news_impact
from core.config import settings
from core.llm_pricing import compute_cost
from services.ai_trading._helpers import _get_task_llm, _news_direction, record_llm_role
from services.ai_trading._market_data import fetch_context_ohlcv, maybe_chart
from services.ai_trading._models import SharedMarketContext

if TYPE_CHECKING:
    from db.models import Account
    from services.ai_trading._models import StrategyOverrides
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)


@dataclass
class SignalPhaseResult:
    """All outputs from the signal phase needed by the post-signal pipeline steps."""
    signal: TradingSignal
    mt5_symbol: str
    candles: list[dict]
    indicators: dict
    current_price: float
    llm_result: LLMAnalysisResult | None
    rule_based: bool
    news_signal: str | None
    built_shared_ctx: SharedMarketContext | None  # None only on fast-path reuse


async def run_signal_phase(
    *,
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    strategy_id: int | None,
    strategy_overrides: "StrategyOverrides | None",
    strategy_instance: object | None,
    shared_ctx: SharedMarketContext | None,
    open_positions: list[dict],
    recent_signals: list[dict],
    trade_history_context: str | None,
    candles: list[dict],
    indicators: dict,
    current_price: float,
    mt5_symbol: str,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> SignalPhaseResult:
    """Run the signal phase for this pipeline call.

    Fast path: if shared_ctx is provided, skip OHLCV/LLM entirely and reuse
    the pre-computed signal (secondary account in a group job).

    Normal path: risk pre-check → rule-based strategy (if configured) →
    LLM analysis (if not rule-based).
    """
    # ── Fast path: secondary group account ───────────────────────────────────
    if shared_ctx is not None:
        signal = shared_ctx.signal.model_copy()
        await tracer.record(
            "shared_signal_received",
            output_data={
                "action": signal.action,
                "confidence": signal.confidence,
                "rationale": signal.rationale[:200] if signal.rationale else "",
                "source": "llm" if shared_ctx.llm_result else "rule",
            },
        )
        return SignalPhaseResult(
            signal=signal,
            mt5_symbol=shared_ctx.mt5_symbol,
            candles=shared_ctx.candles,
            indicators=shared_ctx.indicators,
            current_price=shared_ctx.current_price,
            llm_result=shared_ctx.llm_result,
            rule_based=shared_ctx.llm_result is None,
            news_signal=shared_ctx.news_signal,
            built_shared_ctx=None,
        )

    news_signal: str | None = None

    # ── Risk limit pre-check ─────────────────────────────────────────────────
    t0 = time.monotonic()
    from services.risk_manager import check_position_limit, check_rate_limit, load_risk_config

    risk_cfg = await load_risk_config(db)
    exceeded_pos, pos_reason = check_position_limit(open_positions, risk_cfg)
    exceeded_rate, rate_reason = False, ""
    if not exceeded_pos:
        exceeded_rate, rate_reason = await check_rate_limit(symbol, risk_cfg, db)

    is_risk_blocked = exceeded_pos or exceeded_rate
    blocked_reason = pos_reason if exceeded_pos else rate_reason

    await tracer.record(
        "risk_limit_pre_check",
        output_data={"blocked": is_risk_blocked, "reason": blocked_reason},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

    # ── Risk block → force HOLD ───────────────────────────────────────────────
    if is_risk_blocked:
        hold_signal = TradingSignal(
            action="HOLD",
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            confidence=1.0,
            rationale=f"Risk limit reached: {blocked_reason} — skipping analysis.",
            timeframe=tf_upper,
        )
        built_ctx = SharedMarketContext(
            symbol=symbol, mt5_symbol=mt5_symbol, timeframe=tf_upper,
            candles=candles, indicators=indicators, current_price=current_price or 0.0,
            signal=hold_signal, llm_result=None, news_signal=None,
        )
        return SignalPhaseResult(
            signal=hold_signal, mt5_symbol=mt5_symbol, candles=candles,
            indicators=indicators, current_price=current_price or 0.0,
            llm_result=None, rule_based=True, news_signal=None,
            built_shared_ctx=built_ctx,
        )

    # ── Rule-based path ───────────────────────────────────────────────────────
    if strategy_instance is not None:
        t0 = time.monotonic()
        market_data = {
            "symbol": symbol, "timeframe": tf_upper,
            "current_price": current_price or 0,
            "candles": candles, "indicators": indicators,
            "open_positions": open_positions, "recent_signals": recent_signals,
        }
        try:
            rule_result = strategy_instance.generate_signal(market_data)
        except Exception as exc:
            logger.exception(
                "generate_signal raised | strategy=%s | %s",
                type(strategy_instance).__name__, exc,
            )
            rule_result = None

        if rule_result is not None:
            await tracer.record(
                "rule_signal",
                output_data={
                    "strategy": type(strategy_instance).__name__,
                    "action": rule_result.get("action"),
                    "confidence": rule_result.get("confidence"),
                    "rationale": str(rule_result.get("rationale", ""))[:200],
                },
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            signal = TradingSignal(**rule_result)
            built_ctx = SharedMarketContext(
                symbol=symbol, mt5_symbol=mt5_symbol, timeframe=tf_upper,
                candles=candles, indicators=indicators, current_price=current_price or 0.0,
                signal=signal, llm_result=None, news_signal=None,
            )
            return SignalPhaseResult(
                signal=signal, mt5_symbol=mt5_symbol, candles=candles,
                indicators=indicators, current_price=current_price or 0.0,
                llm_result=None, rule_based=True, news_signal=None,
                built_shared_ctx=built_ctx,
            )

    # ── LLM analysis path ─────────────────────────────────────────────────────
    llm_result, news_signal = await _run_llm_analysis(
        account=account,
        account_id=account_id,
        symbol=symbol,
        tf_upper=tf_upper,
        strategy_id=strategy_id,
        strategy_overrides=strategy_overrides,
        candles=candles,
        indicators=indicators,
        current_price=current_price,
        mt5_symbol=mt5_symbol,
        open_positions=open_positions,
        recent_signals=recent_signals,
        trade_history_context=trade_history_context,
        db=db,
        tracer=tracer,
    )

    signal = llm_result.signal
    built_ctx = SharedMarketContext(
        symbol=symbol, mt5_symbol=mt5_symbol, timeframe=tf_upper,
        candles=candles, indicators=indicators, current_price=current_price or 0.0,
        signal=signal, llm_result=llm_result, news_signal=news_signal,
    )
    return SignalPhaseResult(
        signal=signal, mt5_symbol=mt5_symbol, candles=candles,
        indicators=indicators, current_price=current_price or 0.0,
        llm_result=llm_result, rule_based=False, news_signal=news_signal,
        built_shared_ctx=built_ctx,
    )


async def _run_llm_analysis(
    *,
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    strategy_id: int | None,
    strategy_overrides: "StrategyOverrides | None",
    candles: list[dict],
    indicators: dict,
    current_price: float | None,
    mt5_symbol: str,
    open_positions: list[dict],
    recent_signals: list[dict],
    trade_history_context: str | None,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> tuple[LLMAnalysisResult, str | None]:
    """Run the 3-role LLM pipeline and return (llm_result, news_signal).

    news_signal is non-None only when strategy_overrides.news_filter=True and a
    high-impact event was found within 60 minutes.

    Raises:
        AnalysisResult (implicitly via early return in caller) when news filter
        blocks the trade — handled in run_signal_phase.
    """
    # ── Per-role LLM assignments ──────────────────────────────────────────────
    ma_llm = await _get_task_llm("market_analysis", db)
    cv_llm = await _get_task_llm("vision", db)
    ed_llm = await _get_task_llm("execution_decision", db)
    na_llm = (
        await _get_task_llm("news_analysis", db)
        if strategy_overrides and strategy_overrides.news_filter
        else None
    )

    # ── News analysis gate ────────────────────────────────────────────────────
    news_signal: str | None = None
    if strategy_overrides and strategy_overrides.news_filter:
        from services.market_context import fetch_high_impact_events  # lazy import

        news_events = await fetch_high_impact_events([symbol], minutes=60)
        await tracer.record(
            "news_fetch",
            output_data={
                "events_found": len(news_events),
                "events": [
                    {"time": e["time"], "currency": e["currency"],
                     "title": e["title"], "impact": e["impact"]}
                    for e in news_events
                ],
                "llm_will_run": bool(news_events),
            },
        )
        if news_events:
            t0_news = time.monotonic()
            news_result = await analyze_news_impact(
                events=news_events, symbol=symbol, llm=na_llm,
            )
            dur_news = int((time.monotonic() - t0_news) * 1000)
            news_signal = news_result.signal
            step_id_news = await tracer.record(
                "news_analysis",
                output_data={
                    "signal": news_result.signal,
                    "reasoning": news_result.reasoning,
                    "events_count": len(news_events),
                },
                duration_ms=dur_news,
            )
            if news_result.role_result is not None:
                rr = news_result.role_result
                await tracer.record_llm_call(
                    role="news_analysis",
                    provider=rr.provider,
                    model=rr.model,
                    input_tokens=rr.input_tokens,
                    output_tokens=rr.output_tokens,
                    total_tokens=rr.total_tokens,
                    cost_usd=compute_cost(rr.provider, rr.model, rr.input_tokens or 0, rr.output_tokens or 0),
                    duration_ms=rr.duration_ms,
                    pipeline_step_id=step_id_news,
                )

    # ── Context TF candles + chart ────────────────────────────────────────────
    context_ohlcv = await fetch_context_ohlcv(
        account=account,
        account_id=account_id,
        symbol=symbol,
        primary_tf=tf_upper,
        strategy_id=strategy_id,
        db=db,
    )
    chart_b64 = maybe_chart(candles, symbol, tf_upper)

    # ── Core LLM call ─────────────────────────────────────────────────────────
    t0 = time.monotonic()
    llm_result: LLMAnalysisResult = await analyze_market(
        symbol=symbol,
        timeframe=tf_upper,
        current_price=current_price or 0,
        indicators=indicators,
        ohlcv=candles,
        chart_analysis=chart_b64,
        open_positions=open_positions,
        recent_signals=recent_signals,
        news_context=await _fetch_news_ctx_str(symbol),
        trade_history_context=trade_history_context,
        system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
        market_analysis_llm=ma_llm,
        chart_vision_llm=cv_llm,
        execution_decision_llm=ed_llm,
        context_ohlcv=context_ohlcv if context_ohlcv else None,
    )
    _ = t0  # duration tracked per-role below

    # ── News filter gate ──────────────────────────────────────────────────────
    if news_signal and news_signal != "HOLD":
        market_dir = _news_direction(llm_result.signal.action)
        if market_dir != "HOLD" and market_dir != news_signal:
            await tracer.record(
                "news_filter_blocked",
                output_data={
                    "news_signal": news_signal,
                    "market_signal": llm_result.signal.action,
                    "reason": (
                        f"News analysis ({news_signal}) contradicts "
                        f"market analysis ({market_dir}) — trade skipped"
                    ),
                },
            )
            logger.info(
                "News filter blocked trade | symbol=%s news=%s market=%s",
                symbol, news_signal, market_dir,
            )
            # Mutate signal to HOLD so the caller can persist + return early
            llm_result.signal.action = "HOLD"
            return llm_result, news_signal

    # ── Record per-role token usage ───────────────────────────────────────────
    await record_llm_role(tracer, llm_result.market_analysis, "market_analysis_llm", "market_analysis", {"symbol": symbol, "timeframe": tf_upper})
    if llm_result.chart_vision is not None:
        await record_llm_role(tracer, llm_result.chart_vision, "chart_vision_llm", "chart_vision", {"symbol": symbol, "has_image": True, "chart_b64": chart_b64})
    if llm_result.indicator_agent is not None:
        await record_llm_role(tracer, llm_result.indicator_agent, "indicator_agent_llm", "indicator_agent", {"symbol": symbol, "timeframe": tf_upper})
    if llm_result.pattern_agent is not None:
        await record_llm_role(tracer, llm_result.pattern_agent, "pattern_agent_llm", "pattern_agent", {"symbol": symbol, "has_chart": True, "chart_b64": chart_b64})
    if llm_result.trend_agent is not None:
        tl_b64 = getattr(llm_result, "trendline_chart_b64", None)
        await record_llm_role(tracer, llm_result.trend_agent, "trend_agent_llm", "trend_agent", {"symbol": symbol, "has_trendline_chart": True, **({"chart_b64": tl_b64} if tl_b64 else {})})
    await record_llm_role(tracer, llm_result.execution_decision, "execution_decision_llm", "execution_decision", {"action": llm_result.signal.action, "confidence": llm_result.signal.confidence})

    return llm_result, news_signal


async def _fetch_news_ctx_str(symbol: str) -> str | None:
    """Thin wrapper that fetches news context string (used inside LLM call)."""
    if not getattr(settings, "news_enabled", False):
        return None
    try:
        from services.market_context import fetch_upcoming_events, format_news_context
        events = await fetch_upcoming_events([symbol])
        return format_news_context(events) or None
    except Exception:
        return None
```

- [ ] **Step 2: Verify it parses**

```bash
cd backend && uv run python -c "from services.ai_trading._signal import run_signal_phase, SignalPhaseResult; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_trading/_signal.py
git commit -m "refactor(ai-trading): extract _signal (risk check, rule-based, LLM analysis)"
```

---

## Task 6: Extract `_execution.py`

**Files:**
- Create: `backend/services/ai_trading/_execution.py`

Extracts from `_run_pipeline`:
- Lines 1044–1136 (steps 14–15): lot size computation and `OrderRequest` building
- Lines 1138–1183 (step 16a): MT5 order execution
- Lines 1195–1224 (step 16b): `Trade` + `AIJournal` persistence

- [ ] **Step 1: Create `_execution.py`**

```python
# backend/services/ai_trading/_execution.py
"""Order execution: lot size, OrderRequest, MT5 dispatch, Trade + AIJournal persistence."""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import LLMAnalysisResult, TradingSignal
from core.config import settings
from core.security import decrypt
from db.models import AIJournal, Trade
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor, OrderRequest, pending_expiry_hours
from services.ai_trading._helpers import _calculate_lot_size
from services.alerting import send_alert
from services.ai_trading._models import AnalysisResult, SharedMarketContext
from strategies.base_strategy import direction_from_action

if TYPE_CHECKING:
    from db.models import Account
    from services.ai_trading._models import StrategyOverrides
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)


async def compute_lot_size(
    account: "Account",
    account_id: int,
    signal: TradingSignal,
    mt5_symbol: str,
    strategy_overrides: "StrategyOverrides | None",
    tracer: "PipelineTracer",
) -> float:
    """Compute effective lot size.

    Priority: strategy_overrides.lot_size > risk-based calculation > account.max_lot_size.
    """
    t0 = time.monotonic()
    sl_pips: float | None = None
    pip_value_per_lot: float | None = None
    balance: float | None = None

    if strategy_overrides and strategy_overrides.lot_size is not None:
        effective_lot_size = strategy_overrides.lot_size
    else:
        effective_lot_size = account.max_lot_size  # safe fallback
        try:
            password = decrypt(account.password_encrypted)
            creds = AccountCredentials(
                login=account.login,
                password=password,
                server=account.server,
                path=account.mt5_path or settings.mt5_path,
            )
            async with MT5Bridge(creds) as bridge:
                acct_info = await bridge.get_account_info()
                sym_info = await bridge.get_symbol_info(mt5_symbol)
            if acct_info and sym_info:
                balance = float(acct_info.get("balance", 0))
                tick_value = float(sym_info.get("trade_tick_value", 0))
                tick_size = float(sym_info.get("trade_tick_size", 0))
                pip_size = tick_size * 10 if tick_size > 0 else 0.0001
                sl_distance = abs((signal.entry or 0) - (signal.stop_loss or 0))
                sl_pips = sl_distance / pip_size if pip_size > 0 else 0
                pip_value_per_lot = tick_value
                effective_lot_size = _calculate_lot_size(
                    balance=balance,
                    risk_pct=account.risk_pct,
                    sl_pips=sl_pips,
                    pip_value_per_lot=pip_value_per_lot,
                    max_lot=account.max_lot_size,
                )
                logger.info(
                    "Lot size calculated | account_id=%s balance=%.2f risk_pct=%.3f "
                    "sl_pips=%.1f pip_val=%.4f → lot=%.2f",
                    account_id, balance, account.risk_pct,
                    sl_pips, pip_value_per_lot, effective_lot_size,
                )
        except Exception as exc:
            logger.warning(
                "Dynamic lot size failed — using max_lot_size fallback | account_id=%s | %s",
                account_id, exc,
            )

    await tracer.record(
        "lot_size_calculated",
        output_data={
            "effective_lot_size": effective_lot_size,
            "max_lot_size": account.max_lot_size,
            "risk_pct": account.risk_pct,
            "sl_pips": sl_pips,
            "pip_value_per_lot": pip_value_per_lot,
            "balance": balance,
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return effective_lot_size


async def build_order_request(
    signal: TradingSignal,
    mt5_symbol: str,
    effective_lot_size: float,
    timeframe: str,
    account_id: int,
    strategy_id: int | None,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> tuple[OrderRequest, str]:
    """Build an `OrderRequest` from the signal and return (order_req, source_name)."""
    source = "ai"
    if strategy_id:
        from db.models import Strategy
        strat_rec = await db.get(Strategy, strategy_id)
        if strat_rec:
            source = strat_rec.name

    expiry_hours = pending_expiry_hours(timeframe) * getattr(signal, "expiry_multiplier", 1.0)
    order_req = OrderRequest(
        symbol=mt5_symbol,
        action=signal.action,
        volume=effective_lot_size,
        entry_price=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        comment=source[:64],
        expiration_hours=expiry_hours,
    )
    await tracer.record(
        "order_built",
        input_data={
            "symbol": mt5_symbol,
            "action": signal.action,
            "volume": effective_lot_size,
            "entry": signal.entry,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "expiration_hours": expiry_hours,
            "comment": source[:64],
        },
    )
    return order_req, source


async def execute_mt5_order(
    account: "Account",
    order_req: OrderRequest,
    signal: TradingSignal,
    journal: AIJournal,
    built_shared_ctx: SharedMarketContext | None,
    tracer: "PipelineTracer",
) -> object | None:
    """Connect MT5 and place the order. Returns order_result or None on failure.

    On failure, records the error step, finalizes the tracer, and returns None
    so the caller can return early with order_placed=False.
    """
    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login,
        password=password,
        server=account.server,
        path=account.mt5_path or settings.mt5_path,
    )
    t0 = time.monotonic()
    try:
        async with MT5Bridge(creds) as bridge:
            executor = MT5Executor(bridge)
            order_result = await executor.place_order(
                order_req, dry_run=account.paper_trade_enabled,
            )
    except (RuntimeError, ConnectionError) as exc:
        logger.exception("MT5 error during order execution | %s", exc)
        await tracer.record(
            "mt5_executed", status="error",
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
        return None

    if not order_result.success:
        logger.error("Order failed | error=%s", order_result.error)
        await tracer.record(
            "mt5_executed", status="error",
            output_data={"success": False, "error": order_result.error},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        await send_alert(
            f"*Order Failed*\n"
            f"Account: {account.id} | {signal.action} {order_req.symbol}\n"
            f"Error: {order_result.error}"
        )
        tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
        return None

    await tracer.record(
        "mt5_executed",
        output_data={
            "success": True,
            "ticket": order_result.ticket,
            "paper_trade": account.paper_trade_enabled,
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return order_result


async def persist_trade(
    account_id: int,
    signal: TradingSignal,
    order_result: object,
    effective_lot_size: float,
    symbol: str,
    strategy_id: int | None,
    source: str,
    paper_trade: bool,
    db: AsyncSession,
    journal: AIJournal,
) -> Trade:
    """Persist a `Trade` row and link it back to the `AIJournal` entry."""
    action = signal.action.upper()
    is_pending = action in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
    order_type = (
        "limit" if "LIMIT" in action
        else "stop" if "STOP" in action
        else "market"
    )
    trade = Trade(
        account_id=account_id,
        ticket=order_result.ticket,
        symbol=symbol,
        direction=direction_from_action(signal.action),
        volume=effective_lot_size,
        entry_price=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        opened_at=datetime.now(UTC),
        source=source,
        is_paper_trade=paper_trade,
        strategy_id=strategy_id,
        order_type=order_type,
        order_status="pending" if is_pending else "filled",
    )
    db.add(trade)
    await db.flush()
    journal.trade_id = trade.id
    await db.commit()
    await db.refresh(trade)
    return trade
```

- [ ] **Step 2: Verify it parses**

```bash
cd backend && uv run python -c "from services.ai_trading._execution import compute_lot_size, build_order_request, execute_mt5_order, persist_trade; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_trading/_execution.py
git commit -m "refactor(ai-trading): extract _execution (lot size, order build, MT5, persist)"
```

---

## Task 7: Write `_service.py`, finalize `__init__.py`, delete original

**Files:**
- Create: `backend/services/ai_trading/_service.py`
- Modify: `backend/services/ai_trading/__init__.py`
- Delete: `backend/services/ai_trading.py`

This is the final assembly step. `_run_pipeline` becomes a clean ~120-line orchestrator that calls into the modules extracted in Tasks 1–6. All existing tests must pass after this task.

- [ ] **Step 1: Verify existing tests before touching anything**

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Note the baseline pass/fail count. All currently-passing tests must still pass after this task.

- [ ] **Step 2: Create `_service.py`**

```python
# backend/services/ai_trading/_service.py
"""AITradingService — orchestrates the full AI trading pipeline."""
from __future__ import annotations

import json
import logging
import time

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.ws import broadcast
from core.config import settings
from db.models import AIJournal
from services.ai_trading._context import (
    build_trade_history_context,
    fetch_open_positions,
    fetch_recent_signals,
)
from services.ai_trading._execution import (
    build_order_request,
    compute_lot_size,
    execute_mt5_order,
    persist_trade,
)
from services.ai_trading._market_data import (
    compute_indicators,
    fetch_ohlcv,
    resolve_timeframe,
)
from services.ai_trading._models import AnalysisResult, SharedMarketContext, StrategyOverrides
from services.ai_trading._signal import SignalPhaseResult, run_signal_phase
from services.alerting import send_alert
from services.kill_switch import is_active as kill_switch_active
from services.pipeline_tracer import PipelineTracer
from db.redis import check_llm_rate_limit

logger = logging.getLogger(__name__)


class AITradingService:
    async def analyze_and_trade(
        self,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None = None,
        strategy_overrides: StrategyOverrides | None = None,
        strategy_instance: object | None = None,
        shared_ctx: SharedMarketContext | None = None,
    ) -> AnalysisResult:
        """Run the full AI analysis → optional trade execution pipeline."""
        async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
            return await self._run_pipeline(
                tracer, account_id, symbol, timeframe, db,
                strategy_id, strategy_overrides, strategy_instance,
                shared_ctx=shared_ctx,
            )

    async def _run_pipeline(
        self,
        tracer: PipelineTracer,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None,
        strategy_overrides: StrategyOverrides | None,
        strategy_instance: object | None = None,
        shared_ctx: SharedMarketContext | None = None,
    ) -> AnalysisResult:
        """Full instrumented pipeline — every step recorded to PipelineTracer."""

        # ── 1. Load account ───────────────────────────────────────────────────
        t0 = time.monotonic()
        from db.models import Account
        account: Account | None = await db.get(Account, account_id)
        if not account or not account.is_active:
            await tracer.record(
                "account_loaded", status="error",
                error="Account not found or inactive",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            tracer.finalize(status="failed")
            raise HTTPException(status_code=404, detail="Account not found")
        await tracer.record(
            "account_loaded",
            output_data={
                "name": account.name,
                "auto_trade_enabled": account.auto_trade_enabled,
                "max_lot_size": account.max_lot_size,
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 2. Kill switch (fail-fast) ────────────────────────────────────────
        t0 = time.monotonic()
        ks_early = kill_switch_active()
        await tracer.record(
            "kill_switch_check",
            output_data={"active": ks_early},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        if ks_early:
            logger.warning(
                "Kill switch active — aborting pipeline | account_id=%s symbol=%s",
                account_id, symbol,
            )
            tracer.finalize(status="failed")
            raise HTTPException(status_code=503, detail="Kill switch is active — trading halted")

        # ── 3. Rate limit check (LLM path only) ──────────────────────────────
        if strategy_instance is None and shared_ctx is None:
            t0 = time.monotonic()
            allowed = await check_llm_rate_limit(account_id)
            if not allowed:
                await tracer.record(
                    "rate_limit_check", status="error",
                    output_data={"allowed": False},
                    error="LLM rate limit exceeded",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                tracer.finalize(status="failed")
                raise HTTPException(
                    status_code=429,
                    detail="LLM rate limit exceeded — max 10 calls per 60 seconds per account",
                )
            await tracer.record(
                "rate_limit_check",
                output_data={"allowed": True},
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        # ── 3.5 Fast path: shared context (secondary group account) ──────────
        # The remaining steps (4–8) are skipped; signal_phase handles the fast path.
        tf_upper, tf_int = resolve_timeframe(timeframe) if shared_ctx is None else (timeframe.upper(), 0)

        candles: list[dict] = []
        indicators: dict = {}
        current_price: float | None = None
        mt5_symbol: str = symbol
        open_positions: list[dict] = []
        recent_signals_list: list[dict] = []
        trade_history_context: str | None = None

        if shared_ctx is None:
            # ── 4. OHLCV fetch + market open check ───────────────────────────
            candles, mt5_symbol, current_price = await fetch_ohlcv(
                account=account, account_id=account_id,
                symbol=symbol, tf_upper=tf_upper, tf_int=tf_int,
                tracer=tracer,
            )

            # ── 5. Indicators ─────────────────────────────────────────────────
            t0 = time.monotonic()
            indicators = compute_indicators(candles)
            await tracer.record(
                "indicators_computed",
                output_data=indicators,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

            # ── 6. Position context + recent signals ──────────────────────────
            open_positions = await fetch_open_positions(account, account_id, tracer)
            recent_signals_list = await fetch_recent_signals(account_id, symbol, db, tracer)

            # ── 6.5 Trade history + RAG ───────────────────────────────────────
            trade_history_context = await build_trade_history_context(
                account, account_id, symbol, tf_upper, db, tracer,
            )

        # ── 7–8. Signal phase (rule-based, LLM, or fast-path reuse) ──────────
        sp: SignalPhaseResult = await run_signal_phase(
            account=account,
            account_id=account_id,
            symbol=symbol,
            tf_upper=tf_upper,
            strategy_id=strategy_id,
            strategy_overrides=strategy_overrides,
            strategy_instance=strategy_instance,
            shared_ctx=shared_ctx,
            open_positions=open_positions,
            recent_signals=recent_signals_list,
            trade_history_context=trade_history_context,
            candles=candles,
            indicators=indicators,
            current_price=current_price or 0.0,
            mt5_symbol=mt5_symbol,
            db=db,
            tracer=tracer,
        )
        signal = sp.signal
        mt5_symbol = sp.mt5_symbol
        candles = sp.candles
        indicators = sp.indicators
        current_price = sp.current_price
        llm_result = sp.llm_result
        rule_based = sp.rule_based
        _built_shared_ctx = sp.built_shared_ctx

        # ── 9. Confidence gate ────────────────────────────────────────────────
        action_before = signal.action
        if signal.confidence < settings.llm_confidence_threshold:
            logger.info(
                "Signal downgraded to HOLD — confidence %.2f below threshold %.2f | symbol=%s",
                signal.confidence, settings.llm_confidence_threshold, symbol,
            )
            signal.action = "HOLD"
        await tracer.record(
            "confidence_gate",
            input_data={"confidence": signal.confidence, "threshold": settings.llm_confidence_threshold},
            output_data={"action_before": action_before, "action_after": signal.action},
        )
        logger.info(
            "Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
            symbol, signal.action, signal.confidence, signal.timeframe,
        )

        # ── 9. Persist AIJournal ──────────────────────────────────────────────
        t0 = time.monotonic()
        _skip_analysis = shared_ctx is not None
        journal = AIJournal(
            account_id=account_id,
            trade_id=None,
            symbol=symbol,
            timeframe=tf_upper,
            signal=signal.action,
            confidence=signal.confidence,
            rationale=signal.rationale,
            indicators_snapshot=json.dumps(indicators),
            llm_provider="group_llm" if _skip_analysis else (
                "rule_based" if rule_based else (
                    llm_result.execution_decision.provider if llm_result is not None else settings.llm_provider
                )
            ),
            model_name="shared" if _skip_analysis else (
                type(strategy_instance).__name__ if rule_based
                else (llm_result.execution_decision.model if llm_result is not None else "")
            ),
            strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)
        await tracer.record(
            "journal_saved",
            output_data={"journal_id": journal.id},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 10. Broadcast ai_signal ───────────────────────────────────────────
        await broadcast(account_id, "ai_signal", {
            "journal_id": journal.id,
            "symbol": symbol,
            "timeframe": tf_upper,
            "action": signal.action,
            "confidence": signal.confidence,
            "rationale": signal.rationale,
            "entry": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        # ── 11. HOLD early exit ───────────────────────────────────────────────
        if signal.action == "HOLD":
            await tracer.record("kill_switch_check", output_data={"active": False, "skipped": "HOLD signal"})
            logger.info("Signal HOLD — no order | account_id=%s symbol=%s", account_id, symbol)
            tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id, shared_ctx=_built_shared_ctx)

        # ── 12. Kill switch re-check ──────────────────────────────────────────
        ks_active = kill_switch_active()
        await tracer.record("kill_switch_check", output_data={"active": ks_active})
        if ks_active:
            logger.warning("Kill switch active — signal saved but order skipped | account_id=%s", account_id)
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id, shared_ctx=_built_shared_ctx)

        # ── 13. Auto-trade check ──────────────────────────────────────────────
        if not account.auto_trade_enabled:
            await tracer.record(
                "auto_trade_check", status="skipped",
                output_data={"auto_trade_enabled": False},
                error="Auto-trade is disabled — signal saved but no order placed",
            )
            logger.info("Auto-trade disabled — order skipped | account_id=%s", account_id)
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id, shared_ctx=_built_shared_ctx)

        # ── 14–15. Lot size + OrderRequest ───────────────────────────────────
        effective_lot_size = await compute_lot_size(
            account=account, account_id=account_id,
            signal=signal, mt5_symbol=mt5_symbol,
            strategy_overrides=strategy_overrides,
            tracer=tracer,
        )
        order_req, source = await build_order_request(
            signal=signal, mt5_symbol=mt5_symbol,
            effective_lot_size=effective_lot_size,
            timeframe=timeframe, account_id=account_id,
            strategy_id=strategy_id, db=db, tracer=tracer,
        )

        # ── 16. Execute ───────────────────────────────────────────────────────
        order_result = await execute_mt5_order(
            account=account, order_req=order_req,
            signal=signal, journal=journal,
            built_shared_ctx=_built_shared_ctx,
            tracer=tracer,
        )
        if order_result is None:
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id, shared_ctx=_built_shared_ctx)

        # ── 16b. Persist Trade ────────────────────────────────────────────────
        trade = await persist_trade(
            account_id=account_id, signal=signal, order_result=order_result,
            effective_lot_size=effective_lot_size, symbol=symbol,
            strategy_id=strategy_id, source=source,
            paper_trade=account.paper_trade_enabled, db=db, journal=journal,
        )

        # ── 17. Broadcast trade_opened ────────────────────────────────────────
        await broadcast(account_id, "trade_opened", {
            "ticket": order_result.ticket,
            "symbol": symbol,
            "direction": trade.direction,
            "action": signal.action,
            "volume": effective_lot_size,
            "entry_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        # ── 18. Telegram alert ────────────────────────────────────────────────
        t0 = time.monotonic()
        paper_tag = " _(paper)_" if account.paper_trade_enabled else ""
        alert_msg = (
            f"*Trade Placed{paper_tag}*\n"
            f"Account: {account_id} | {signal.action} {effective_lot_size} {symbol}\n"
            f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"Ticket: {order_result.ticket}"
        )
        await send_alert(alert_msg)
        await tracer.record(
            "telegram_sent",
            output_data={"sent": True, "preview": alert_msg[:100]},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        logger.info(
            "Trade executed | account_id=%s symbol=%s direction=%s ticket=%s",
            account_id, symbol, signal.action, order_result.ticket,
        )
        tracer.finalize(
            status="completed", final_action=signal.action,
            journal_id=journal.id, trade_id=trade.id,
        )
        return AnalysisResult(
            signal=signal, order_placed=True,
            ticket=order_result.ticket, journal_id=journal.id,
            shared_ctx=_built_shared_ctx,
        )
```

- [ ] **Step 3: Update `__init__.py`** (already correct from Task 1 — verify it's unchanged)

```python
# backend/services/ai_trading/__init__.py
from services.ai_trading._models import AnalysisResult, SharedMarketContext, StrategyOverrides
from services.ai_trading._service import AITradingService

__all__ = ["AITradingService", "AnalysisResult", "SharedMarketContext", "StrategyOverrides"]
```

- [ ] **Step 4: Verify the package imports cleanly**

```bash
cd backend && uv run python -c "from services.ai_trading import AITradingService, AnalysisResult, SharedMarketContext, StrategyOverrides; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Delete the original file**

```bash
rm backend/services/ai_trading.py
```

> After deletion the only source of `AITradingService` is the package. Any import statement that previously worked must still work.

- [ ] **Step 6: Run the full test suite**

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: same pass count as the baseline recorded in Step 1. Fix any import errors before committing.

- [ ] **Step 7: Commit**

```bash
git add backend/services/ai_trading/_service.py backend/services/ai_trading/__init__.py
git rm backend/services/ai_trading.py
git commit -m "refactor(ai-trading): complete package split — delete monolith, wire service orchestrator"
```

---

## Self-Review

**Spec coverage:**
- ✅ All 18 pipeline steps preserved in `_service.py._run_pipeline`
- ✅ Shared-context fast path preserved in `_signal.py.run_signal_phase`
- ✅ News filter gate preserved in `_signal.py._run_llm_analysis`
- ✅ Risk pre-check preserved in `_signal.py.run_signal_phase`
- ✅ `__init__.py` re-exports match original public surface
- ✅ Deferred `import asyncio` moved to module top in `_market_data.py`
- ✅ `import dataclasses as _dc` (unused, line 284) dropped entirely
- ✅ `import math` moved to module top in `_market_data.py`
- ✅ `_record_llm_role` extracted from nested closure, `tracer` made explicit

**Type consistency:**
- `SignalPhaseResult.built_shared_ctx` is `SharedMarketContext | None` — callers in `_service.py` correctly handle `None` (fast-path secondary accounts return `None` because the shared context was provided, not built here)
- `execute_mt5_order` returns `object | None` (returns `None` on failure); caller checks `if order_result is None`
- `build_order_request` returns `tuple[OrderRequest, str]` — destructured as `order_req, source`

**Placeholder scan:** No TBDs, no "add validation", no "similar to" references. All function bodies shown in full.
