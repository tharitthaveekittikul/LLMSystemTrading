"""Execution helpers: lot-size computation, order building, MT5 order placement, trade persistence."""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import TradingSignal
from core.config import settings
from core.security import decrypt
from db.models import AIJournal, Trade
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import (
    TRADE_RETCODE_INVALID_PRICE,
    MT5Executor,
    OrderRequest,
    OrderResult,
    pending_expiry_hours,
)
from services.ai_trading._helpers import _calculate_lot_size
from services.alerting import send_alert
from strategies.base_strategy import direction_from_action

if TYPE_CHECKING:
    from db.models import Account
    from services.ai_trading._models import SharedMarketContext, StrategyOverrides
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
    """Compute effective lot size. Records lot_size_calculated tracer step."""
    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login, password=password,
        server=account.server, path=account.mt5_path or settings.mt5_path,
    )

    t0 = time.monotonic()
    sl_pips: float | None = None
    pip_value_per_lot: float | None = None
    balance: float | None = None

    if strategy_overrides and strategy_overrides.lot_size is not None:
        effective_lot_size = strategy_overrides.lot_size
    else:
        effective_lot_size = account.max_lot_size  # safe fallback
        try:
            async with MT5Bridge(creds) as lot_bridge:
                acct_info = await lot_bridge.get_account_info()
                sym_info = await lot_bridge.get_symbol_info(mt5_symbol)
            if acct_info and sym_info:
                balance = float(acct_info.get("balance", 0))
                tick_value = float(sym_info.get("trade_tick_value", 0))
                tick_size = float(sym_info.get("trade_tick_size", 0))
                # Normalise SL distance to pips (1 pip = 10 × tick_size for 5-digit brokers)
                pip_size = tick_size * 10 if tick_size > 0 else 0.0001
                sl_distance = abs((signal.entry or 0) - (signal.stop_loss or 0))
                sl_pips = sl_distance / pip_size if pip_size > 0 else 0
                # trade_tick_value is already in account currency for 1 pip on 1 lot
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
                    "sl_pips=%.1f pip_val=%.4f -> lot=%.2f",
                    account_id, balance, account.risk_pct, sl_pips, pip_value_per_lot, effective_lot_size,
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
            "formula": f"{balance} * {account.risk_pct} * {sl_pips} * {pip_value_per_lot} / {account.max_lot_size} = {effective_lot_size}",
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
    """Build OrderRequest + resolve source name. Records order_built tracer step.
    Returns: (order_req, source_name)
    """
    _source = "ai"
    if strategy_id:
        from db.models import Strategy as _Strategy
        _strat_rec = await db.get(_Strategy, strategy_id)
        if _strat_rec:
            _source = _strat_rec.name

    _expiry_hours = pending_expiry_hours(timeframe) * getattr(signal, "expiry_multiplier", 1.0)
    order_req = OrderRequest(
        symbol=mt5_symbol,  # broker-specific name resolved at OHLCV fetch time
        action=signal.action,
        volume=effective_lot_size,
        entry_price=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        comment=_source[:64],
        expiration_hours=_expiry_hours,
    )
    await tracer.record(
        "order_built",
        input_data={
            "mt5_symbol": mt5_symbol,
            "action": signal.action,
            "volume": effective_lot_size,
            "entry": signal.entry,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "expiration_hours": _expiry_hours,
            "expiry_multiplier": getattr(signal, "expiry_multiplier", 1.0),
            "comment": _source[:64],
        },
    )
    return order_req, _source


async def execute_mt5_order(
    account: "Account",
    order_req: "OrderRequest",
    signal: TradingSignal,
    journal: "AIJournal",
    built_shared_ctx: "SharedMarketContext | None",
    tracer: "PipelineTracer",
) -> "OrderResult | None":
    """Place MT5 order. Returns order_result on success, None on failure.

    On failure: records mt5_executed error step, calls tracer.finalize(status='failed'), returns None.
    """
    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login, password=password,
        server=account.server, path=account.mt5_path or settings.mt5_path,
    )

    t0 = time.monotonic()
    try:
        async with MT5Bridge(creds) as bridge:
            executor = MT5Executor(bridge)
            order_result = await executor.place_order(
                order_req, dry_run=account.paper_trade_enabled
            )
    except (RuntimeError, ConnectionError) as exc:
        logger.exception("MT5 error during order execution | account_id=%s | %s", account.id, exc)
        await tracer.record(
            "mt5_executed", status="error",
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
        return None

    if not order_result.success:
        if order_result.retcode == TRADE_RETCODE_INVALID_PRICE:
            # Stale pending entry — return to caller for LLM re-request (no finalize)
            logger.warning(
                "Stale pending entry — returning for re-request | account_id=%s symbol=%s error=%s",
                account.id, order_req.symbol, order_result.error,
            )
            await tracer.record(
                "mt5_executed", status="stale",
                output_data={
                    "success": False,
                    "retcode": TRADE_RETCODE_INVALID_PRICE,
                    "error": order_result.error,
                },
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            return order_result

        logger.error(
            "Order failed | account_id=%s symbol=%s error=%s",
            account.id, order_req.symbol, order_result.error,
        )
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
    journal: "AIJournal",
) -> "Trade":
    """Persist Trade row and link AIJournal.trade_id. Returns Trade."""
    _action = signal.action.upper()
    _is_pending = _action in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
    _order_type = (
        "limit" if "LIMIT" in _action
        else "stop" if "STOP" in _action
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
        order_type=_order_type,
        order_status="pending" if _is_pending else "filled",
    )
    db.add(trade)
    await db.flush()

    journal.trade_id = trade.id
    await db.commit()
    await db.refresh(trade)
    return trade
