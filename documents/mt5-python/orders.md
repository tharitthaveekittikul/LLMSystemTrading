# MT5 Python — Order Execution

Source: https://www.mql5.com/en/docs/python_metatrader5

---

## order_send()

Send a trading request to the MT5 trade server.

```python
order_send(request)
```

### Parameters

`request` — a dict matching the `MqlTradeRequest` structure.

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | int | Yes | Trade action type (see constants below) |
| `symbol` | str | Yes | Instrument name |
| `volume` | float | Yes | Lots |
| `type` | int | Yes | Order type (see constants below) |
| `price` | float | Cond. | Execution price (required for non-market orders) |
| `sl` | float | No | Stop loss price |
| `tp` | float | No | Take profit price |
| `deviation` | int | No | Max price deviation in points |
| `magic` | int | No | EA magic number for tracking |
| `comment` | str | No | Order comment (max 31 chars) |
| `type_filling` | int | No | Fill policy (see constants below) |
| `type_time` | int | No | Expiration type |
| `expiration` | datetime | Cond. | Expiration time (required for `ORDER_TIME_SPECIFIED`) |
| `order` | int | Cond. | Order ticket (required for modify/remove) |
| `position` | int | Cond. | Position ticket (required when closing a position) |
| `stoplimit` | float | Cond. | Limit price for stop-limit orders |
| `position_by` | int | No | Opposite position ticket for close-by |

### Action Constants

| Constant | Description |
|----------|-------------|
| `mt5.TRADE_ACTION_DEAL` | Market order (open or close) |
| `mt5.TRADE_ACTION_PENDING` | Place pending order |
| `mt5.TRADE_ACTION_SLTP` | Modify SL/TP on open position |
| `mt5.TRADE_ACTION_MODIFY` | Modify pending order |
| `mt5.TRADE_ACTION_REMOVE` | Cancel pending order |
| `mt5.TRADE_ACTION_CLOSE_BY` | Close position by opposite |

### Order Type Constants

| Constant | Description |
|----------|-------------|
| `mt5.ORDER_TYPE_BUY` | Market buy |
| `mt5.ORDER_TYPE_SELL` | Market sell |
| `mt5.ORDER_TYPE_BUY_LIMIT` | Buy limit pending |
| `mt5.ORDER_TYPE_SELL_LIMIT` | Sell limit pending |
| `mt5.ORDER_TYPE_BUY_STOP` | Buy stop pending |
| `mt5.ORDER_TYPE_SELL_STOP` | Sell stop pending |
| `mt5.ORDER_TYPE_BUY_STOP_LIMIT` | Buy stop-limit |
| `mt5.ORDER_TYPE_SELL_STOP_LIMIT` | Sell stop-limit |

### Fill Policy Constants

| Constant | Description |
|----------|-------------|
| `mt5.ORDER_FILLING_FOK` | Fill or Kill — entire volume or cancel |
| `mt5.ORDER_FILLING_IOC` | Immediate or Cancel — fill available, cancel rest |
| `mt5.ORDER_FILLING_RETURN` | Return remaining volume as new order |

### Time Constants

| Constant | Description |
|----------|-------------|
| `mt5.ORDER_TIME_GTC` | Good Till Cancel |
| `mt5.ORDER_TIME_DAY` | Good Till end of day |
| `mt5.ORDER_TIME_SPECIFIED` | Valid until `expiration` time |

### Return Value

`MqlTradeResult` named tuple:

| Field | Type | Description |
|-------|------|-------------|
| `retcode` | int | Result code — **10009 = success** |
| `deal` | int | Deal ticket |
| `order` | int | Order ticket |
| `volume` | float | Executed volume |
| `price` | float | Execution price |
| `bid` | float | Current bid |
| `ask` | float | Current ask |
| `comment` | str | Server comment |
| `request_id` | int | Request ID |
| `retcode_external` | int | External system code |

**`TRADE_RETCODE_DONE = 10009`** — the only success code.

### Example — Open and close market order

```python
import MetaTrader5 as mt5
import time

if not mt5.initialize():
    quit()

symbol = "USDJPY"

# Ensure symbol is in MarketWatch
mt5.symbol_select(symbol, True)

symbol_info = mt5.symbol_info(symbol)
point = symbol_info.point
price = mt5.symbol_info_tick(symbol).ask

request = {
    "action":       mt5.TRADE_ACTION_DEAL,
    "symbol":       symbol,
    "volume":       0.1,
    "type":         mt5.ORDER_TYPE_BUY,
    "price":        price,
    "sl":           price - 100 * point,
    "tp":           price + 100 * point,
    "deviation":    20,
    "magic":        100001,
    "comment":      "llm_signal",
    "type_time":    mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_RETURN,
}

result = mt5.order_send(request)
if result.retcode == mt5.TRADE_RETCODE_DONE:
    position_id = result.order
    print(f"Buy opened: ticket={position_id} price={result.price}")

    time.sleep(2)

    # Close the position
    close_price = mt5.symbol_info_tick(symbol).bid
    close_request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       0.1,
        "type":         mt5.ORDER_TYPE_SELL,
        "position":     position_id,   # REQUIRED to close existing position
        "price":        close_price,
        "deviation":    20,
        "magic":        100001,
        "comment":      "llm_close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    close_result = mt5.order_send(close_request)
    if close_result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"Position {position_id} closed at {close_result.price}")
    else:
        print(f"Close failed: {close_result.retcode} {close_result.comment}")
else:
    print(f"Order failed: {result.retcode} {result.comment}")

mt5.shutdown()
```

### Notes

- Always validate with `order_check()` before `order_send()` in production.
- `ORDER_FILLING_RETURN` is the safest default for most brokers.
- Check broker's accepted filling modes with `symbol_info().filling_mode`.
- `kill_switch` must be checked **before** calling `order_send()` (project rule).
