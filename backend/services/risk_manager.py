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
