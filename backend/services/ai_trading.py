"""AI Trading Service — full pipeline from market data to executed order.

Pipeline per call:
  1. Load account credentials from DB
  2. Redis rate limit check (10 LLM calls / 60s per account)
  3. Redis OHLCV cache (TTL by timeframe) — fetch from MT5 on miss
  4. Fetch open positions + recent signals + trade history for LLM memory context
  5. orchestrator.analyze_market() -> TradingSignal (with position/news context)
  6. Persist to AIJournal (trade_id=None initially)
  7. Broadcast ai_signal WebSocket event
  8. If BUY/SELL: check kill switch -> MT5Executor -> persist Trade -> update AIJournal
  9. Broadcast trade_opened (if order placed)
"""
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel as PydanticBase
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import TradingSignal, analyze_market
from api.routes.ws import broadcast
from core.config import settings
from core.security import decrypt
from db.models import Account, AIJournal, Trade
from db.redis import check_llm_rate_limit, get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor, OrderRequest
from services.alerting import send_alert
from services.history_sync import HistoryService
from services.kill_switch import is_active as kill_switch_active

logger = logging.getLogger(__name__)

# MT5 TIMEFRAME integer constants (from MetaTrader5 Python library)
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

# OHLCV cache TTL by timeframe (seconds)
_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}


class StrategyOverrides(PydanticBase):
    """Per-strategy parameter overrides supplied by the scheduler."""
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool = True
    custom_prompt: str | None = None


@dataclass
class AnalysisResult:
    signal: TradingSignal
    order_placed: bool
    ticket: int | None
    journal_id: int


class AITradingService:
    async def analyze_and_trade(
        self,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None = None,
        strategy_overrides: "StrategyOverrides | None" = None,
    ) -> AnalysisResult:
        """Run the full AI analysis -> optional trade execution pipeline."""
        # 1. Load account
        account: Account | None = await db.get(Account, account_id)
        if not account or not account.is_active:
            raise HTTPException(status_code=404, detail="Account not found")

        # 2. Rate limit
        allowed = await check_llm_rate_limit(account_id)
        if not allowed:
            logger.warning("LLM rate limit exceeded | account_id=%s", account_id)
            raise HTTPException(
                status_code=429,
                detail="LLM rate limit exceeded — max 10 calls per 60 seconds per account",
            )

        # 3. Resolve timeframe int
        tf_upper = timeframe.upper()
        tf_int = _TIMEFRAME_MAP.get(tf_upper)
        if tf_int is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown timeframe '{timeframe}'. Supported: {list(_TIMEFRAME_MAP)}",
            )

        # 4. Fetch / cache OHLCV
        candles = await get_candle_cache(account_id, symbol, tf_upper)
        current_price: float | None = None

        if candles is None:
            logger.info("OHLCV cache miss | account_id=%s symbol=%s tf=%s", account_id, symbol, tf_upper)
            password = decrypt(account.password_encrypted)
            creds = AccountCredentials(
                login=account.login,
                password=password,
                server=account.server,
                path=account.mt5_path or settings.mt5_path,
            )
            try:
                async with MT5Bridge(creds) as bridge:
                    candles = await bridge.get_rates(symbol, tf_int, 50)
                    tick = await bridge.get_tick(symbol)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            except ConnectionError as exc:
                raise HTTPException(status_code=502, detail=str(exc))

            if not candles:
                raise HTTPException(status_code=502, detail=f"MT5 returned no candles for {symbol} {timeframe}")

            ttl = _CACHE_TTL.get(tf_upper, 60)
            await set_candle_cache(account_id, symbol, tf_upper, candles, ttl)

            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

        if current_price is None and candles:
            current_price = float(candles[-1].get("close", 0))

        # 5. Compute basic indicators
        closes = [float(c.get("close", 0)) for c in candles[-20:]]
        indicators = {
            "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
            "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
            "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
            "candle_count": len(candles),
        }

        # 6. Fetch position context and recent signals for LLM memory
        open_positions: list[dict] = []
        try:
            pos_password = decrypt(account.password_encrypted)
            pos_creds = AccountCredentials(
                login=account.login,
                password=pos_password,
                server=account.server,
                path=account.mt5_path or settings.mt5_path,
            )
            async with MT5Bridge(pos_creds) as pos_bridge:
                raw_positions = await pos_bridge.get_positions()
            open_positions = [
                {
                    "symbol": p.get("symbol", ""),
                    "direction": "BUY" if p.get("type") == 0 else "SELL",
                    "volume": p.get("volume", 0),
                    "profit": p.get("profit", 0),
                }
                for p in raw_positions
            ]
        except Exception as exc:
            logger.warning(
                "Could not fetch positions for LLM context | account_id=%s: %s", account_id, exc
            )

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
            logger.warning(
                "Could not fetch recent signals for LLM context | account_id=%s: %s", account_id, exc
            )

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
            logger.warning(
                "Could not fetch trade history for LLM context | account_id=%s: %s", account_id, exc
            )

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
            trade_history_context=trade_history_context,
            system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
        )

        # 8. Persist AIJournal
        journal = AIJournal(
            account_id=account_id,
            trade_id=None,
            symbol=symbol,
            timeframe=tf_upper,
            signal=signal.action,
            confidence=signal.confidence,
            rationale=signal.rationale,
            indicators_snapshot=json.dumps(indicators),
            llm_provider=settings.llm_provider,
            model_name="",
            strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)

        # 9. Broadcast ai_signal
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

        # 10. Skip execution for HOLD or kill switch active
        if signal.action == "HOLD":
            logger.info("Signal HOLD — no order | account_id=%s symbol=%s", account_id, symbol)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        if kill_switch_active():
            logger.warning(
                "Kill switch active — signal saved but order skipped | account_id=%s symbol=%s",
                account_id, symbol,
            )
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        # Skip execution if auto-trade disabled for this account
        if not account.auto_trade_enabled:
            logger.info(
                "Auto-trade disabled — signal saved but order skipped | account_id=%s",
                account_id,
            )
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        # 11. Build order request
        effective_lot_size = (
            strategy_overrides.lot_size
            if strategy_overrides and strategy_overrides.lot_size is not None
            else account.max_lot_size
        )
        order_req = OrderRequest(
            symbol=symbol,
            direction=signal.action,
            volume=effective_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            comment="AI-Trade",
        )

        # 12. Connect MT5 and execute
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )
        try:
            async with MT5Bridge(creds) as bridge:
                executor = MT5Executor(bridge)
                order_result = await executor.place_order(
                    order_req, dry_run=account.paper_trade_enabled
                )
        except (RuntimeError, ConnectionError) as exc:
            logger.error("MT5 error during order execution | account_id=%s | %s", account_id, exc)
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        if not order_result.success:
            logger.error(
                "Order failed | account_id=%s symbol=%s error=%s",
                account_id, symbol, order_result.error,
            )
            await send_alert(
                f"*Order Failed*\n"
                f"Account: {account_id} | {signal.action} {symbol}\n"
                f"Error: {order_result.error}"
            )
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)

        # 13. Persist Trade row
        trade = Trade(
            account_id=account_id,
            ticket=order_result.ticket,
            symbol=symbol,
            direction=signal.action,
            volume=effective_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            opened_at=datetime.now(UTC),
            source="ai",
            is_paper_trade=account.paper_trade_enabled,
            strategy_id=strategy_id,
        )
        db.add(trade)
        await db.flush()

        journal.trade_id = trade.id
        await db.commit()
        await db.refresh(trade)

        # 14. Broadcast trade_opened
        await broadcast(account_id, "trade_opened", {
            "ticket": order_result.ticket,
            "symbol": symbol,
            "direction": signal.action,
            "volume": effective_lot_size,
            "entry_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        paper_tag = " _(paper)_" if account.paper_trade_enabled else ""
        await send_alert(
            f"*Trade Placed{paper_tag}*\n"
            f"Account: {account_id} | {signal.action} {effective_lot_size} {symbol}\n"
            f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"Ticket: {order_result.ticket}"
        )
        logger.info(
            "Trade executed | account_id=%s symbol=%s direction=%s ticket=%s",
            account_id, symbol, signal.action, order_result.ticket,
        )
        return AnalysisResult(
            signal=signal,
            order_placed=True,
            ticket=order_result.ticket,
            journal_id=journal.id,
        )
