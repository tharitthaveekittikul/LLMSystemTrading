"""Market data helpers for the AI trading pipeline.

Covers:
- Timeframe resolution
- OHLCV fetch (Redis cache → MT5 on miss) + market-open check
- Indicator computation via pandas-ta
- Context timeframe OHLCV fetch
- Optional chart generation
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.redis import get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from services.ai_trading._helpers import _CACHE_TTL, _TIMEFRAME_MAP

if TYPE_CHECKING:
    from db.models import Account
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────


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

    Returns: (candles, mt5_symbol, current_price)
    Raises: HTTPException 503 (market closed / MT5 error), 502 (no candles)
    """
    t0 = time.monotonic()
    candles = await get_candle_cache(account_id, symbol, tf_upper)
    current_price: float | None = None
    ohlcv_source = "cache"
    mt5_symbol: str = symbol
    tick: dict | None = None

    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login, password=password,
        server=account.server, path=account.mt5_path or settings.mt5_path,
    )
    try:
        async with MT5Bridge(creds) as bridge:
            # Resolve broker-specific symbol name (e.g. EURUSD → EURUSD.s)
            mt5_symbol = await bridge.get_broker_symbol(symbol)

            # ── Market open check (fail-fast before any LLM cost) ────────
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

            # ── OHLCV fetch (reuses open bridge; skipped on cache hit) ───
            if candles is None:
                ohlcv_source = "mt5"
                logger.info("OHLCV cache miss | account_id=%s symbol=%s tf=%s", account_id, symbol, tf_upper)
                for _attempt in range(2):
                    candles = await bridge.get_rates(mt5_symbol, tf_int, 250)
                    if candles:
                        break
                    if _attempt == 0:
                        logger.warning(
                            "MT5 returned no candles (attempt 1) — retrying in 1 s | symbol=%s tf=%s",
                            mt5_symbol, tf_upper,
                        )
                        await asyncio.sleep(1)
                tick = await bridge.get_tick(mt5_symbol)

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
        if tick:
            current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

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
    """Compute pandas-ta indicators. Falls back to basic if pandas-ta unavailable or < 200 candles."""
    try:
        import pandas as pd
        import pandas_ta  # noqa: F401 — registers the `.ta` accessor on DataFrame

        # Build DataFrame from MT5 candles
        df = pd.DataFrame(candles)
        if not df.empty and len(df) >= 200:  # Need enough data for EMA200
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)

            # Compute indicators inline via pandas-ta
            df.ta.ema(length=50, append=True)
            df.ta.ema(length=200, append=True)
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.atr(length=14, append=True)
            df.ta.bbands(length=20, std=2, append=True)

            # Extract the latest row
            latest = df.iloc[-1].to_dict()

            # Build rich indicator context
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
            # Fallback if pandas-ta calculation cannot be performed due to insufficient data
            logger.warning("Insufficient candles for pandas-ta calculations (need >= 200). Using basic.")
            closes = [float(c.get("close", 0)) for c in candles[-20:]]
            indicators = {
                "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                "candle_count": len(candles),
            }
    except ImportError:
        logger.warning("pandas or pandas-ta not installed. Falling back to basic indicators.")
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        indicators = {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }
    except Exception as e:
        logger.exception(f"Error computing advanced indicators: {e}")
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        indicators = {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }

    # Sanitize output from NaNs created by pandas (json.dumps will fail on NaN)
    indicators = {k: (0.0 if isinstance(v, float) and math.isnan(v) else v) for k, v in indicators.items()}

    return indicators


async def fetch_context_ohlcv(
    account: "Account",
    account_id: int,
    symbol: str,
    primary_tf: str,
    strategy_id: int | None,
    db: AsyncSession,
) -> dict[str, list[dict]]:
    """Fetch OHLCV for context timeframes from strategy DB record."""
    context_ohlcv: dict[str, list[dict]] = {}
    if not strategy_id:
        return context_ohlcv

    from db.models import Strategy

    strat_db = await db.get(Strategy, strategy_id)
    if not strat_db or not strat_db.context_tfs or strat_db.context_tfs == "[]":
        return context_ohlcv

    try:
        ctx_tfs = json.loads(strat_db.context_tfs)
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login, password=password,
            server=account.server, path=account.mt5_path or settings.mt5_path,
        )
        for ctx_tf in ctx_tfs:
            ctx_tf_upper = ctx_tf.upper()
            if ctx_tf_upper == primary_tf:
                continue  # Skip primary TF
            ctx_candles = await get_candle_cache(account_id, symbol, ctx_tf_upper)
            if ctx_candles is None:
                ctx_tf_int = _TIMEFRAME_MAP.get(ctx_tf_upper)
                if ctx_tf_int is not None:
                    try:
                        async with MT5Bridge(creds) as bridge:
                            mt5_symbol_ctx = await bridge.get_broker_symbol(symbol)
                            ctx_candles = await bridge.get_rates(mt5_symbol_ctx, ctx_tf_int, 20)
                    except Exception as exc:
                        logger.warning("Context TF fetch failed | symbol=%s tf=%s: %s", symbol, ctx_tf_upper, exc)
                        ctx_candles = []
                    if ctx_candles:
                        ttl = _CACHE_TTL.get(ctx_tf_upper, 60)
                        await set_candle_cache(account_id, symbol, ctx_tf_upper, ctx_candles, ttl)
            if ctx_candles:
                context_ohlcv[ctx_tf_upper] = ctx_candles
    except json.JSONDecodeError:
        pass

    return context_ohlcv


def maybe_chart(candles: list[dict], symbol: str, tf_upper: str) -> str | None:
    """Generate base64 OHLCV chart if settings.enable_chart_vision is True."""
    if not settings.enable_chart_vision:
        return None
    from ai.vision import generate_ohlcv_chart
    return generate_ohlcv_chart(candles, symbol, tf_upper)
