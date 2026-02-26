# MT5 Python — Account & Terminal Info

Source: https://www.mql5.com/en/docs/python_metatrader5

---

## terminal_info()

Get status and parameters of the connected MetaTrader 5 terminal.

```python
terminal_info()
```

### Return Value

Named tuple with terminal properties, or `None` on error.

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| **`connected`** | bool | **Terminal→broker connection status. Use as heartbeat.** |
| `community_account` | bool | MQL5.community account linked |
| `community_connection` | bool | Connected to MQL5.community |
| `dlls_allowed` | bool | DLL imports allowed |
| `trade_allowed` | bool | Trading allowed in terminal |
| `tradeapi_disabled` | bool | Trade API disabled flag |
| `build` | int | Terminal build number |
| `maxbars` | int | Max bars in chart history |
| `ping_last` | int | Last ping time (ms) |
| `company` | str | Broker company name |
| `name` | str | Terminal name |
| `language` | str | Terminal language |
| `path` | str | Terminal installation path |
| `data_path` | str | Terminal data folder path |

### Notes

- **`connected` field** is the lightweight broker heartbeat — poll this before each data fetch to detect network drops without waiting for a data call to fail.
- Consolidates `TerminalInfoInteger`, `TerminalInfoDouble`, `TerminalInfoString` in one call.

### Example

```python
import MetaTrader5 as mt5

if not mt5.initialize():
    quit()

info = mt5.terminal_info()
if info is not None:
    print("Broker connected:", info.connected)
    print("Build:", info.build)
    # Access as dict
    d = info._asdict()
    for k, v in d.items():
        print(f"  {k}={v}")

mt5.shutdown()
```

### Heartbeat usage in poll loop

```python
while True:
    info = mt5.terminal_info()
    if not info or not info.connected:
        raise ConnectionError("Broker connection lost")
    account = mt5.account_info()
    # ... fetch and broadcast ...
    time.sleep(5)
```

---

## account_info()

Get current trading account information (balance, equity, margin, etc.).

```python
account_info()
```

### Return Value

Named tuple with account data, or `None` on error.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `login` | int | Account login number |
| `trade_mode` | int | Account type: 0=demo, 1=contest, 2=real |
| `leverage` | int | Account leverage (e.g. 100 = 1:100) |
| `limit_orders` | int | Maximum pending orders allowed |
| `margin_so_mode` | int | Margin call mode |
| `trade_allowed` | bool | Manual trading permitted |
| `trade_expert` | bool | Expert Advisor trading permitted |
| `margin_mode` | int | Margin calculation mode |
| `currency_digits` | int | Decimal places for account currency |
| `fifo_close` | bool | FIFO position closing required |
| `balance` | float | Account balance |
| `credit` | float | Credit amount |
| `profit` | float | Current floating profit/loss |
| `equity` | float | Equity (balance + profit) |
| `margin` | float | Used margin |
| `margin_free` | float | Free margin available |
| `margin_level` | float | Margin level % (equity/margin × 100) |
| `margin_so_call` | float | Margin call level % |
| `margin_so_so` | float | Stop-out level % |
| `margin_initial` | float | Initial margin |
| `margin_maintenance` | float | Maintenance margin |
| `assets` | float | Account assets |
| `liabilities` | float | Account liabilities |
| `commission_blocked` | float | Blocked commission |
| `name` | str | Account holder name |
| `server` | str | Trade server name |
| `currency` | str | Account currency (e.g. "USD") |
| `company` | str | Broker company name |

### Notes

- Must call `initialize()` first.
- Returns `None` if not connected — always check for `None`.
- Use `._asdict()` to convert to a plain dict.

### Example

```python
import MetaTrader5 as mt5

if not mt5.initialize(login=25115284, server="MetaQuotes-Demo", password="4zatlbqx"):
    quit()

info = mt5.account_info()
if info is not None:
    print(f"Balance: {info.balance} {info.currency}")
    print(f"Equity:  {info.equity}")
    print(f"Margin:  {info.margin}  Free: {info.margin_free}")
    print(f"Level:   {info.margin_level:.1f}%")
    print(f"Type:    {'DEMO' if info.trade_mode == 0 else 'REAL'}")
else:
    print("account_info() failed:", mt5.last_error())

mt5.shutdown()
```
