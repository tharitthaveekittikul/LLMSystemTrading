"""Position Maintenance Service — scheduled AI review of open positions and pending orders.

For each eligible position:
  1. Fetch OHLCV (Redis cache by TF)
  2. LLM Role 1: maintenance_technical_analysis
  3. LLM Role 2: maintenance_sentiment_analysis
  4. LLM Role 3: maintenance_decision → HOLD | CLOSE | MODIFY
  5. ConstraintValidator — validate MODIFY against strategy rules
  6. MT5 action (skip / close_position / modify_order)

Every position run is traced via PipelineTracer (task_type="maintenance").
"""
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import review_position
from core.config import settings
from core.llm_pricing import compute_cost
from core.security import decrypt
from db.models import Account, AccountStrategy, Strategy, Trade
from db.redis import get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor
from services.kill_switch import is_active as kill_switch_active
from services.market_context import fetch_upcoming_events, format_news_context
from services.history_sync import HistoryService
from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)

# MT5 timeframe integer map (same as ai_trading.py)
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}

_PIP_SIZE: dict[str, float] = {
    "XAUUSD": 0.1, "XAGUSD": 0.001,
}
_DEFAULT_PIP_SIZE = 0.0001  # standard forex pairs


def _get_pip_size(symbol: str) -> float:
    return _PIP_SIZE.get(symbol.upper(), _DEFAULT_PIP_SIZE)


# ── Constraint Validator ───────────────────────────────────────────────────────

@dataclass
class ConstraintResult:
    passed: bool
    reason: str | None = None


def validate_modify(
    *,
    direction: str,
    entry_price: float,
    current_price: float,
    current_sl: float,
    volume: float,
    balance: float,
    new_sl: float,
    new_tp: float,
    sl_pips: float,
    risk_pct: float,
    symbol: str,
) -> ConstraintResult:
    """Validate an LLM-suggested MODIFY against strategy risk constraints.

    Returns ConstraintResult(passed=True) if all checks pass, or
    ConstraintResult(passed=False, reason=...) with the first violated rule.
    """
    pip_size = _get_pip_size(symbol)

    # 1. Minimum SL distance from current price
    sl_distance = abs(current_price - new_sl)
    min_sl_distance = sl_pips * pip_size
    if sl_distance < min_sl_distance:
        return ConstraintResult(
            passed=False,
            reason=(
                f"new_sl too close: distance={sl_distance:.5f} < "
                f"min={min_sl_distance:.5f} ({sl_pips} pips)"
            ),
        )

    # 2. Trailing stop logic — SL may only move in favorable direction
    entry_to_current = (
        current_price - entry_price if direction == "BUY" else entry_price - current_price
    )
    if entry_to_current >= 0:  # position is at break-even or in profit
        if direction == "BUY" and new_sl < current_sl:
            return ConstraintResult(
                passed=False,
                reason=(
                    f"trailing stop violated: BUY position in profit, "
                    f"new_sl {new_sl} < current_sl {current_sl}"
                ),
            )
        if direction == "SELL" and new_sl > current_sl:
            return ConstraintResult(
                passed=False,
                reason=(
                    f"trailing stop violated: SELL position in profit, "
                    f"new_sl {new_sl} > current_sl {current_sl}"
                ),
            )

    # 3. Max risk per trade: new SL must not risk more than risk_pct of balance
    new_sl_distance_pips = abs(current_price - new_sl) / pip_size
    approx_pip_value = 10.0  # USD per pip per standard lot (approximate)
    max_risk_usd = balance * risk_pct
    actual_risk_usd = new_sl_distance_pips * approx_pip_value * volume
    if actual_risk_usd > max_risk_usd * 1.2:  # 20% tolerance
        return ConstraintResult(
            passed=False,
            reason=(
                f"max risk exceeded: risk={actual_risk_usd:.2f} USD > "
                f"max={max_risk_usd:.2f} USD ({risk_pct * 100:.1f}% of {balance:.2f})"
            ),
        )

    # 4. Minimum R:R — new_tp must be at least 1:1 from entry vs new_sl
    sl_dist = abs(entry_price - new_sl)
    if direction == "BUY":
        tp_dist = abs(new_tp - entry_price)
    else:
        tp_dist = abs(entry_price - new_tp)

    if sl_dist > 0 and tp_dist < sl_dist:
        return ConstraintResult(
            passed=False,
            reason=(
                f"R:R below 1:1: TP distance {tp_dist:.5f} < SL distance {sl_dist:.5f}"
            ),
        )

    return ConstraintResult(passed=True)


# ── PositionMaintenanceService ─────────────────────────────────────────────────

class PositionMaintenanceService:

    async def run_maintenance_sweep(self, db: AsyncSession) -> None:
        """Entry point called by APScheduler. Sweeps all active accounts."""
        logger.info(
            "Maintenance sweep started | interval=%dmin",
            settings.maintenance_interval_minutes,
        )

        if not settings.maintenance_task_enabled:
            logger.info("Maintenance task globally disabled — skipping sweep")
            return

        result = await db.execute(
            select(Account).where(Account.is_active.is_(True))
        )
        accounts = result.scalars().all()

        totals: dict[str, int] = {"hold": 0, "close": 0, "modify": 0, "skip": 0, "error": 0}

        for account in accounts:
            try:
                counts = await self._process_account(account, db)
                for k, v in counts.items():
                    totals[k] = totals.get(k, 0) + v
            except Exception:
                logger.exception("Maintenance sweep failed for account=%d", account.id)
                totals["error"] += 1

        logger.info(
            "Maintenance sweep complete | HOLD=%d CLOSE=%d MODIFY=%d SKIP=%d ERR=%d",
            totals["hold"], totals["close"], totals["modify"],
            totals["skip"], totals["error"],
        )

    async def _process_account(
        self, account: Account, db: AsyncSession
    ) -> dict[str, int]:
        """Process all eligible positions/orders for a single account."""
        counts: dict[str, int] = {"hold": 0, "close": 0, "modify": 0, "skip": 0, "error": 0}

        if kill_switch_active():
            logger.warning("Maintenance account=%d skipped — kill switch active", account.id)
            counts["skip"] += 999
            return counts

        # Fetch active strategy bindings for this account
        strat_result = await db.execute(
            select(AccountStrategy).where(
                AccountStrategy.account_id == account.id,
                AccountStrategy.is_active.is_(True),
            )
        )
        bindings = strat_result.scalars().all()

        # Build set of maintenance-enabled strategy IDs
        strategy_ids: set[int] = set()
        strategies_by_id: dict[int, Strategy] = {}
        for binding in bindings:
            strat = await db.get(Strategy, binding.strategy_id)
            if strat and strat.is_active and strat.maintenance_enabled:
                strategy_ids.add(strat.id)
                strategies_by_id[strat.id] = strat

        if not strategy_ids:
            logger.debug("Account=%d: no maintenance-enabled strategies", account.id)
            return counts

        # Fetch eligible trades (open, maintenance_enabled, linked to maintenance strategies)
        trade_result = await db.execute(
            select(Trade).where(
                Trade.account_id == account.id,
                Trade.order_status.in_(["filled", "pending"]),
                Trade.closed_at.is_(None),
                Trade.strategy_id.in_(list(strategy_ids)),
                Trade.maintenance_enabled.is_(True),
            )
        )
        eligible_trades = trade_result.scalars().all()

        if not eligible_trades:
            logger.info("Account=%d: 0 eligible positions for maintenance", account.id)
            return counts

        logger.info(
            "Account=%d (%s): %d positions eligible for maintenance",
            account.id, account.name, len(eligible_trades),
        )

        # Connect to MT5 once for this account
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )

        try:
            async with MT5Bridge(creds) as bridge:
                mt5_positions = await bridge.get_positions()
                mt5_orders = await bridge.get_orders()
                mt5_by_ticket: dict[int, dict] = {
                    p["ticket"]: p for p in mt5_positions + mt5_orders
                }

                account_info = await bridge.get_account_info()
                balance = account_info["balance"] if account_info else 10000.0

                for trade in eligible_trades:
                    mt5_pos = mt5_by_ticket.get(trade.ticket)
                    strategy = strategies_by_id.get(trade.strategy_id)

                    if not mt5_pos or not strategy:
                        counts["skip"] += 1
                        continue

                    try:
                        action = await self._run_single_maintenance(
                            trade=trade,
                            mt5_pos=mt5_pos,
                            strategy=strategy,
                            bridge=bridge,
                            balance=balance,
                            account=account,
                            db=db,
                        )
                        counts[action.lower()] = counts.get(action.lower(), 0) + 1
                    except Exception:
                        logger.exception(
                            "Maintenance failed | account=%d ticket=%d",
                            account.id, trade.ticket,
                        )
                        counts["error"] += 1
                        await db.rollback()

        except ConnectionError as exc:
            logger.warning("Maintenance account=%d MT5 unavailable: %s", account.id, exc)
            counts["error"] += len(eligible_trades)

        return counts

    async def _run_single_maintenance(
        self,
        *,
        trade: Trade,
        mt5_pos: dict,
        strategy: Strategy,
        bridge: MT5Bridge,
        balance: float,
        account: Account,
        db: AsyncSession,
    ) -> str:
        """Run maintenance pipeline for one position. Returns the final action taken."""
        symbol = trade.symbol
        timeframe = strategy.timeframe or "H1"

        async with PipelineTracer(
            account.id, symbol, timeframe, task_type="maintenance", strategy_id=strategy.id
        ) as tracer:
            # Step 1: Fetch OHLCV
            t0 = time.monotonic()
            tf_int = _TIMEFRAME_MAP.get(timeframe, 16385)
            cache_key = f"ohlcv:{symbol}:{timeframe}"
            cache_ttl = _CACHE_TTL.get(timeframe, 300)

            ohlcv = await get_candle_cache(cache_key)
            if not ohlcv:
                ohlcv = await bridge.get_rates(symbol, tf_int, 50)
                if ohlcv:
                    await set_candle_cache(cache_key, ohlcv, cache_ttl)

            await tracer.record(
                "ohlcv_fetch",
                output_data={"count": len(ohlcv) if ohlcv else 0},
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

            if not ohlcv:
                tracer.finalize(status="skipped", final_action="HOLD")
                return "HOLD"

            # Step 2: Compute indicators + build context
            closes = [c["close"] for c in ohlcv[-20:]]
            sma20 = sum(closes) / len(closes) if closes else 0.0
            indicators = {
                "sma20": round(sma20, 5),
                "high_20": round(max(c["high"] for c in ohlcv[-20:]), 5),
                "low_20": round(min(c["low"] for c in ohlcv[-20:]), 5),
            }
            tick = await bridge.get_tick(symbol)
            current_price = tick["bid"] if tick else (closes[-1] if closes else 0.0)

            opened_at = trade.opened_at
            duration_hours = (
                (datetime.now(UTC) - opened_at).total_seconds() / 3600
                if opened_at else 0.0
            )
            position_ctx = {
                "ticket": trade.ticket,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "current_price": current_price,
                "current_sl": mt5_pos.get("sl", trade.stop_loss),
                "current_tp": mt5_pos.get("tp", trade.take_profit),
                "unrealized_pnl": mt5_pos.get("profit", 0.0),
                "volume": trade.volume,
                "duration_hours": round(duration_hours, 1),
                "order_type": trade.order_type,
                "order_status": trade.order_status,
            }
            strategy_params = {
                "sl_pips": strategy.sl_pips or 20.0,
                "tp_pips": strategy.tp_pips or 40.0,
                "risk_pct": account.risk_pct,
                "max_lot_size": account.max_lot_size,
            }

            await tracer.record(
                "context_built",
                output_data={"position": position_ctx, "indicators": indicators},
                duration_ms=0,
            )

            # Step 3: Fetch optional context (news + history)
            news_ctx = None
            if settings.news_enabled:
                try:
                    events = await fetch_upcoming_events([symbol])
                    news_ctx = format_news_context(events) or None
                except Exception as exc:
                    logger.debug("News context fetch failed (non-critical): %s", exc)

            history_ctx = None
            try:
                hs = HistoryService(bridge, db)
                history_ctx = await hs.get_history_context(account.id, symbol, days=14)
            except Exception as exc:
                logger.debug("History context fetch failed (non-critical): %s", exc)

            # Step 4: 3-role LLM pipeline
            t0 = time.monotonic()
            result = await review_position(
                symbol=symbol,
                timeframe=timeframe,
                ohlcv=ohlcv,
                indicators=indicators,
                position=position_ctx,
                strategy_params=strategy_params,
                news_context=news_ctx,
                trade_history_context=history_ctx,
            )

            # Record each LLM role
            for role_result, role_name in [
                (result.technical_analysis, "maintenance_technical"),
                (result.sentiment_analysis, "maintenance_sentiment"),
                (result.maintenance_decision, "maintenance_decision"),
            ]:
                step_id = await tracer.record(
                    role_name,
                    output_data={"content": role_result.content},
                    duration_ms=role_result.duration_ms,
                )
                cost = compute_cost(
                    role_result.provider,
                    role_result.model,
                    role_result.input_tokens or 0,
                    role_result.output_tokens or 0,
                )
                await tracer.record_llm_call(
                    role=role_name,
                    provider=role_result.provider,
                    model=role_result.model,
                    input_tokens=role_result.input_tokens,
                    output_tokens=role_result.output_tokens,
                    total_tokens=role_result.total_tokens,
                    cost_usd=cost,
                    duration_ms=role_result.duration_ms,
                    pipeline_step_id=step_id,
                )

            decision = result.decision

            # Step 5: Constraint validation for MODIFY
            final_action = decision.action
            constraint_reason: str | None = None

            if (
                decision.action == "MODIFY"
                and decision.new_sl is not None
                and decision.new_tp is not None
            ):
                current_sl = mt5_pos.get("sl", trade.stop_loss)
                cv = validate_modify(
                    direction=trade.direction,
                    entry_price=trade.entry_price,
                    current_price=current_price,
                    current_sl=current_sl,
                    volume=trade.volume,
                    balance=balance,
                    new_sl=decision.new_sl,
                    new_tp=decision.new_tp,
                    sl_pips=strategy.sl_pips or 20.0,
                    risk_pct=account.risk_pct,
                    symbol=symbol,
                )
                if not cv.passed:
                    logger.info(
                        "MODIFY downgraded to HOLD (constraint: %s) | ticket=%d",
                        cv.reason, trade.ticket,
                    )
                    final_action = "HOLD"
                    constraint_reason = cv.reason
                    await tracer.record(
                        "constraint_rejected",
                        status="ok",
                        output_data={
                            "original_action": "MODIFY",
                            "downgraded_to": "HOLD",
                            "reason": cv.reason,
                            "llm_new_sl": decision.new_sl,
                            "llm_new_tp": decision.new_tp,
                        },
                    )

            # Step 6: MT5 action
            executor = MT5Executor(bridge)
            dry_run = account.paper_trade_enabled

            if final_action == "CLOSE":
                t0 = time.monotonic()
                mt5_result = await executor.close_position(
                    ticket=trade.ticket,
                    symbol=symbol,
                    volume=trade.volume,
                    dry_run=dry_run,
                )
                await tracer.record(
                    "mt5_close",
                    status="ok" if mt5_result.success else "error",
                    output_data={"success": mt5_result.success, "ticket": mt5_result.ticket},
                    error=mt5_result.error,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                logger.info(
                    "Maintenance CLOSE | account=%d ticket=%d symbol=%s success=%s",
                    account.id, trade.ticket, symbol, mt5_result.success,
                )

            elif (
                final_action == "MODIFY"
                and decision.new_sl is not None
                and decision.new_tp is not None
            ):
                t0 = time.monotonic()
                mt5_result = await executor.modify_order(
                    ticket=trade.ticket,
                    symbol=symbol,
                    new_sl=decision.new_sl,
                    new_tp=decision.new_tp,
                    dry_run=dry_run,
                )
                if mt5_result.success:
                    trade.stop_loss = decision.new_sl
                    trade.take_profit = decision.new_tp
                    await db.commit()
                await tracer.record(
                    "mt5_modify",
                    status="ok" if mt5_result.success else "error",
                    output_data={
                        "success": mt5_result.success,
                        "new_sl": decision.new_sl,
                        "new_tp": decision.new_tp,
                    },
                    error=mt5_result.error,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                logger.info(
                    "Maintenance MODIFY | account=%d ticket=%d symbol=%s "
                    "sl=%.5f tp=%.5f success=%s",
                    account.id, trade.ticket, symbol,
                    decision.new_sl, decision.new_tp, mt5_result.success,
                )

            else:
                await tracer.record(
                    "maintenance_hold",
                    output_data={
                        "rationale": decision.rationale,
                        "confidence": decision.confidence,
                        "constraint_reason": constraint_reason,
                    },
                )
                logger.info(
                    "Maintenance HOLD | account=%d ticket=%d symbol=%s",
                    account.id, trade.ticket, symbol,
                )

            tracer.finalize(status="completed", final_action=final_action)
            return final_action
