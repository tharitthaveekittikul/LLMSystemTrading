"""MT5 Order Executor — wraps MT5Bridge for trade operations.

Kill switch is checked here as the final gate before every order.
Never import MetaTrader5 directly in this file — use bridge.py.
"""
from dataclasses import dataclass

from mt5.bridge import MT5Bridge
from services.kill_switch import is_active as kill_switch_active

try:
    import MetaTrader5 as mt5  # only for ORDER_TYPE_* constants

    _ORDER_TYPE_BUY = mt5.ORDER_TYPE_BUY
    _ORDER_TYPE_SELL = mt5.ORDER_TYPE_SELL
    _ORDER_FILLING_IOC = mt5.ORDER_FILLING_IOC
except ImportError:
    _ORDER_TYPE_BUY = 0
    _ORDER_TYPE_SELL = 1
    _ORDER_FILLING_IOC = 1


@dataclass
class OrderRequest:
    symbol: str
    direction: str   # BUY | SELL
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    comment: str = "AI-Trade"
    deviation: int = 20  # max price deviation in points


@dataclass
class OrderResult:
    success: bool
    ticket: int | None = None
    error: str | None = None
    retcode: int | None = None


class MT5Executor:
    def __init__(self, bridge: MT5Bridge) -> None:
        self._bridge = bridge

    async def place_order(self, request: OrderRequest) -> OrderResult:
        # ── Kill switch gate (mandatory check) ───────────────────────────────
        if kill_switch_active():
            return OrderResult(success=False, error="Kill switch is active — order rejected")

        order_type = _ORDER_TYPE_BUY if request.direction == "BUY" else _ORDER_TYPE_SELL

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
            "type_filling": _ORDER_FILLING_IOC,
        }

        result = await self._bridge.send_order(mt5_request)
        if not result:
            code, msg = await self._bridge.get_last_error()
            return OrderResult(success=False, error=msg, retcode=code)

        retcode = result.get("retcode", -1)
        if retcode == 10009:  # TRADE_RETCODE_DONE
            return OrderResult(success=True, ticket=result.get("order"), retcode=retcode)

        return OrderResult(
            success=False,
            error=result.get("comment", "Unknown error"),
            retcode=retcode,
        )

    async def close_position(self, ticket: int, symbol: str, volume: float) -> OrderResult:
        if kill_switch_active():
            return OrderResult(success=False, error="Kill switch is active")

        # Fetch current position to determine close direction
        positions = await self._bridge.get_positions(symbol=symbol)
        pos = next((p for p in positions if p["ticket"] == ticket), None)
        if not pos:
            return OrderResult(success=False, error=f"Position {ticket} not found")

        tick = await self._bridge.get_tick(symbol)
        if not tick:
            return OrderResult(success=False, error="Failed to get current price")

        close_type = _ORDER_TYPE_SELL if pos["type"] == 0 else _ORDER_TYPE_BUY
        close_price = tick["bid"] if close_type == _ORDER_TYPE_SELL else tick["ask"]

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
            "type_filling": _ORDER_FILLING_IOC,
        }

        result = await self._bridge.send_order(mt5_request)
        if not result:
            code, msg = await self._bridge.get_last_error()
            return OrderResult(success=False, error=msg, retcode=code)

        retcode = result.get("retcode", -1)
        return OrderResult(
            success=(retcode == 10009),
            ticket=result.get("order"),
            retcode=retcode,
            error=result.get("comment") if retcode != 10009 else None,
        )
