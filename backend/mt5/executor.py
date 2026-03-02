"""MT5 Order Executor — wraps MT5Bridge for trade operations.

Kill switch is checked here as the final gate before every order.
Never import MetaTrader5 directly in this file — use bridge.py.
"""
import logging
import time
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

from core.config import settings
from mt5.bridge import MT5Bridge
from services.kill_switch import is_active as kill_switch_active
from services.risk_manager import exceeds_position_limit

try:
    import MetaTrader5 as mt5  # only for ORDER_TYPE_* constants

    _ORDER_TYPE_BUY = mt5.ORDER_TYPE_BUY
    _ORDER_TYPE_SELL = mt5.ORDER_TYPE_SELL
    _ORDER_FILLING_IOC = mt5.ORDER_FILLING_IOC
except ImportError:
    _ORDER_TYPE_BUY = 0
    _ORDER_TYPE_SELL = 1
    _ORDER_FILLING_IOC = 1

logger = logging.getLogger(__name__)


class OrderRequest(BaseModel):
    """Validated order request.  Raises ValidationError on bad input."""

    symbol: str = Field(..., min_length=1, max_length=20)
    direction: str = Field(..., description="BUY or SELL")
    volume: float = Field(..., gt=0.0, description="Lot size, must be positive")
    entry_price: float = Field(..., gt=0.0)
    stop_loss: float = Field(..., gt=0.0)
    take_profit: float = Field(..., gt=0.0)
    comment: str = Field(default="AI-Trade", max_length=64)
    deviation: int = Field(default=20, ge=0, description="Max price deviation in points")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v.upper() not in {"BUY", "SELL"}:
            raise ValueError("direction must be 'BUY' or 'SELL'")
        return v.upper()


@dataclass
class OrderResult:
    success: bool
    ticket: int | None = None
    error: str | None = None
    retcode: int | None = None


class MT5Executor:
    def __init__(self, bridge: MT5Bridge) -> None:
        self._bridge = bridge

    async def place_order(self, request: OrderRequest, dry_run: bool = False) -> OrderResult:
        # ── Kill switch gate (mandatory check) ───────────────────────────────
        if kill_switch_active():
            logger.warning(
                "Order rejected — kill switch active | symbol=%s direction=%s volume=%s",
                request.symbol, request.direction, request.volume,
            )
            return OrderResult(success=False, error="Kill switch is active — order rejected")

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

        # ── AutoTrading gate ──────────────────────────────────────────────────
        if not await self._bridge.is_autotrading_enabled():
            logger.error(
                "Order rejected — AutoTrading is disabled in the MT5 terminal. "
                "Enable it via the toolbar ▶ AutoTrading button or "
                "Tools → Options → Expert Advisors → Allow automated trading."
            )
            return OrderResult(
                success=False,
                error="AutoTrading disabled by client — enable it in the MT5 terminal",
            )

        # ── Paper trading / dry-run mode ──────────────────────────────────────
        if dry_run:
            fake_ticket = -int(time.time())  # negative — distinguishable from real tickets
            logger.info(
                "DRY RUN order | symbol=%s direction=%s volume=%s fake_ticket=%s",
                request.symbol, request.direction, request.volume, fake_ticket,
            )
            return OrderResult(success=True, ticket=fake_ticket, retcode=10009)

        logger.info(
            "Placing order | symbol=%s direction=%s volume=%s entry=%s sl=%s tp=%s",
            request.symbol, request.direction, request.volume,
            request.entry_price, request.stop_loss, request.take_profit,
        )

        order_type = _ORDER_TYPE_BUY if request.direction == "BUY" else _ORDER_TYPE_SELL
        filling_mode = await self._bridge.get_filling_mode(request.symbol)
        logger.debug("Filling mode for %s: %s", request.symbol, filling_mode)

        mt5_request = {
            "action": 1,  # TRADE_ACTION_DEAL
            "symbol": request.symbol,
            "volume": request.volume,
            "type": order_type,
            "price": request.entry_price,
            "sl": request.stop_loss,
            "tp": request.take_profit,
            "deviation": request.deviation,
            "magic": 20250101,  # EA magic number
            "comment": request.comment,
            "type_time": 0,    # ORDER_TIME_GTC
            "type_filling": filling_mode,
        }

        result = await self._bridge.send_order(mt5_request)
        if not result:
            code, msg = await self._bridge.get_last_error()
            logger.error("Order send failed | symbol=%s | code=%s msg=%s", request.symbol, code, msg)
            return OrderResult(success=False, error=msg, retcode=code)

        retcode = result.get("retcode", -1)
        if retcode == 10009:  # TRADE_RETCODE_DONE
            ticket = result.get("order")
            logger.info(
                "Order placed | symbol=%s direction=%s volume=%s ticket=%s",
                request.symbol, request.direction, request.volume, ticket,
            )
            return OrderResult(success=True, ticket=ticket, retcode=retcode)

        error_msg = result.get("comment", "Unknown error")
        logger.error(
            "Order rejected by broker | symbol=%s retcode=%s error=%s",
            request.symbol, retcode, error_msg,
        )
        return OrderResult(success=False, error=error_msg, retcode=retcode)

    async def close_position(self, ticket: int, symbol: str, volume: float, dry_run: bool = False) -> OrderResult:
        if kill_switch_active():
            logger.warning("Close rejected — kill switch active | ticket=%s symbol=%s", ticket, symbol)
            return OrderResult(success=False, error="Kill switch is active")

        if dry_run:
            logger.info("DRY RUN close | ticket=%s symbol=%s volume=%s", ticket, symbol, volume)
            return OrderResult(success=True, ticket=ticket, retcode=10009)

        logger.info("Closing position | ticket=%s symbol=%s volume=%s", ticket, symbol, volume)

        # Fetch current position to determine close direction
        positions = await self._bridge.get_positions(symbol=symbol)
        pos = next((p for p in positions if p["ticket"] == ticket), None)
        if not pos:
            logger.error("Position not found | ticket=%s symbol=%s", ticket, symbol)
            return OrderResult(success=False, error=f"Position {ticket} not found")

        tick = await self._bridge.get_tick(symbol)
        if not tick:
            logger.error("Failed to get tick for close | symbol=%s", symbol)
            return OrderResult(success=False, error="Failed to get current price")

        close_type = _ORDER_TYPE_SELL if pos["type"] == 0 else _ORDER_TYPE_BUY
        close_price = tick["bid"] if close_type == _ORDER_TYPE_SELL else tick["ask"]
        filling_mode = await self._bridge.get_filling_mode(symbol)

        mt5_request = {
            "action": 1,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "position": ticket,
            "price": close_price,
            "deviation": 20,
            "magic": 20250101,
            "comment": "Close",
            "type_time": 0,
            "type_filling": filling_mode,
        }

        result = await self._bridge.send_order(mt5_request)
        if not result:
            code, msg = await self._bridge.get_last_error()
            logger.error("Close send failed | ticket=%s | code=%s msg=%s", ticket, code, msg)
            return OrderResult(success=False, error=msg, retcode=code)

        retcode = result.get("retcode", -1)
        success = retcode == 10009
        if success:
            logger.info("Position closed | ticket=%s symbol=%s", ticket, symbol)
        else:
            logger.error(
                "Close rejected by broker | ticket=%s retcode=%s error=%s",
                ticket, retcode, result.get("comment"),
            )
        return OrderResult(
            success=success,
            ticket=result.get("order"),
            retcode=retcode,
            error=result.get("comment") if not success else None,
        )
