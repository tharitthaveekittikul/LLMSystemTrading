# MetaTrader 5 Python Integration — Documentation Index

Source: https://www.mql5.com/en/docs/python_metatrader5
Cached: 2026-02-27

## Installation

```bash
pip install MetaTrader5
pip install --upgrade MetaTrader5
pip install pandas matplotlib  # recommended extras
```

## Critical Constraints

- **Windows only** — MT5 communicates with the terminal via Windows IPC (COM/named pipes).
- **NOT thread-safe** — `initialize()` binds to the calling OS thread via COM. All subsequent MT5 calls must run on that **same thread**. Always use `ThreadPoolExecutor(max_workers=1)`.
- **Persistent connection is best practice** — connect once, poll many times, `shutdown()` in finally.
- **Global state** — only one terminal/login active at a time per Python process.

## Function Index

| Category | File | Functions |
|----------|------|-----------|
| Connection | [connection.md](connection.md) | `initialize`, `login`, `shutdown` |
| Terminal & Account | [account-terminal.md](account-terminal.md) | `terminal_info`, `account_info` |
| Market Data | [market-data.md](market-data.md) | `symbol_info_tick`, `symbol_select`, `copy_rates_from_pos` |
| Positions | [positions.md](positions.md) | `positions_get`, `positions_total` |
| Orders | [orders.md](orders.md) | `order_send`, `order_check` |
| Errors | [error-codes.md](error-codes.md) | `last_error` + all error codes |

## Recommended Usage Pattern (in this project)

```python
# All MT5 calls go through a single dedicated thread (bridge.py)
_MT5_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")

# Session lifecycle:
mt5.initialize(path=..., login=..., password=..., server=...)  # once
try:
    while True:
        if not mt5.terminal_info().connected:
            raise ConnectionError("Broker dropped")
        info = mt5.account_info()
        positions = mt5.positions_get()
        time.sleep(5)
finally:
    mt5.shutdown()
```

## Complete Function List

### Connection & Terminal
- `initialize()` – Connect to terminal (slow, call once)
- `login()` – Switch trading account without reconnecting terminal
- `shutdown()` – Close connection (call in finally)
- `version()` – Terminal version tuple
- `last_error()` – Last error code + description

### Account & Terminal Info
- `account_info()` – Balance, equity, margin, leverage, currency, etc.
- `terminal_info()` – Terminal status incl. `connected` (broker heartbeat)

### Symbol Management
- `symbols_total()` – Count of available instruments
- `symbols_get()` – All instruments
- `symbol_info()` – Detailed instrument properties
- `symbol_info_tick()` – Last tick (bid/ask/last/volume)
- `symbol_select()` – Add/remove from MarketWatch (required before tick data)

### Market Depth
- `market_book_add()` – Subscribe to depth changes
- `market_book_get()` – Current depth entries
- `market_book_release()` – Unsubscribe

### Historical Data
- `copy_rates_from()` – OHLCV from date
- `copy_rates_from_pos()` – OHLCV from bar index (0=current)
- `copy_rates_range()` – OHLCV within date range
- `copy_ticks_from()` – Ticks from date
- `copy_ticks_range()` – Ticks within date range

### Order Management
- `orders_total()` – Pending order count
- `orders_get()` – Pending orders (filter by symbol/ticket)
- `order_calc_margin()` – Margin requirement for an order
- `order_calc_profit()` – Estimated profit
- `order_check()` – Validate order before sending
- `order_send()` – Execute trade

### Position Management
- `positions_total()` – Open position count
- `positions_get()` – Open positions (filter by symbol/group/ticket)

### Trading History
- `history_orders_total()` – Historical order count
- `history_orders_get()` – Historical orders
- `history_deals_total()` – Historical deal count
- `history_deals_get()` – Historical deals
