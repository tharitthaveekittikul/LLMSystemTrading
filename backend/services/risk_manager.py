"""Runtime risk checks — toggleable rules with no writes or external I/O.

All pure check functions take a RiskConfig dataclass (loaded by callers).
check_rate_limit is async because it queries the trades table.
load_risk_config() is provided as a convenience loader for callers.
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Snapshot of risk_settings DB row. Passed to all check functions."""
    drawdown_check_enabled: bool = False
    max_drawdown_pct: float = 10.0
    position_limit_enabled: bool = False
    max_open_positions: int = 5
    rate_limit_enabled: bool = False
    rate_limit_max_trades: int = 3
    rate_limit_window_hours: float = 4.0
    hedging_allowed: bool = True


async def load_risk_config(db: AsyncSession) -> RiskConfig:
    """Load singleton risk_settings row from DB. Returns safe defaults if row missing."""
    from db.models import RiskSettings  # local import — avoids circular at module load

    row = (
        await db.execute(select(RiskSettings).where(RiskSettings.id == 1))
    ).scalar_one_or_none()
    if not row:
        logger.warning("risk_settings row not found — using safe defaults (all checks disabled)")
        return RiskConfig()
    return RiskConfig(
        drawdown_check_enabled=row.drawdown_check_enabled,
        max_drawdown_pct=row.max_drawdown_pct,
        position_limit_enabled=row.position_limit_enabled,
        max_open_positions=row.max_open_positions,
        rate_limit_enabled=row.rate_limit_enabled,
        rate_limit_max_trades=row.rate_limit_max_trades,
        rate_limit_window_hours=row.rate_limit_window_hours,
        hedging_allowed=row.hedging_allowed,
    )


# ── Pure check functions (no I/O) ──────────────────────────────────────────

def check_drawdown(equity: float, balance: float, cfg: RiskConfig) -> tuple[bool, str]:
    """Return (exceeded, reason). True → kill switch should fire."""
    if not cfg.drawdown_check_enabled:
        return False, ""
    if balance <= 0:
        return False, ""
    drawdown_pct = (balance - equity) / balance * 100
    if drawdown_pct >= cfg.max_drawdown_pct:
        reason = (
            f"Max drawdown exceeded: {drawdown_pct:.2f}% >= {cfg.max_drawdown_pct:.1f}% "
            f"(equity={equity:.2f}, balance={balance:.2f})"
        )
        logger.warning(reason)
        return True, reason
    return False, ""


def check_position_limit(
    positions: list[dict[str, Any]], cfg: RiskConfig
) -> tuple[bool, str]:
    """Return (exceeded, reason). True → order should be rejected."""
    if not cfg.position_limit_enabled:
        return False, ""
    count = len(positions)
    if count >= cfg.max_open_positions:
        reason = f"Position limit reached: {count}/{cfg.max_open_positions} open positions"
        logger.warning(reason)
        return True, reason
    return False, ""


def check_hedging(
    symbol: str,
    direction: str,
    positions: list[dict[str, Any]],
    cfg: RiskConfig,
) -> tuple[bool, str]:
    """Return (exceeded, reason). True → order rejected (hedging disabled).

    direction: "BUY" or "SELL" (the new trade's underlying direction).
    position type: 0=BUY, 1=SELL (MT5 convention).
    """
    if cfg.hedging_allowed:
        return False, ""
    # Opposite MT5 type for the incoming direction
    opposite_type = 1 if direction == "BUY" else 0
    opposite_label = "SELL" if direction == "BUY" else "BUY"
    for pos in positions:
        if pos.get("symbol") == symbol and pos.get("type") == opposite_type:
            reason = (
                f"Hedging disabled: opposite {opposite_label} position already "
                f"open on {symbol} (ticket={pos.get('ticket')})"
            )
            logger.warning(reason)
            return True, reason
    return False, ""


async def check_rate_limit(
    symbol: str, cfg: RiskConfig, db: AsyncSession
) -> tuple[bool, str]:
    """Return (exceeded, reason). True → order rejected (rate limit hit).

    Counts trades opened on `symbol` within the rolling window.
    Queries the trades table — hedges count toward the limit.
    """
    if not cfg.rate_limit_enabled:
        return False, ""
    from db.models import Trade  # local import — avoids circular at module load

    cutoff = datetime.now(UTC) - timedelta(hours=cfg.rate_limit_window_hours)
    result = await db.execute(
        select(func.count()).select_from(Trade).where(
            Trade.symbol == symbol,
            Trade.opened_at >= cutoff,
        )
    )
    count: int = result.scalar() or 0
    if count >= cfg.rate_limit_max_trades:
        reason = (
            f"Rate limit hit: {count}/{cfg.rate_limit_max_trades} trades on {symbol} "
            f"in the last {cfg.rate_limit_window_hours:.1f}h"
        )
        logger.warning(reason)
        return True, reason
    return False, ""
