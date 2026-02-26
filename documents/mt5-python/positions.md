# MT5 Python — Positions

Source: https://www.mql5.com/en/docs/python_metatrader5

---

## positions_get()

Retrieve open positions with optional filtering.

```python
positions_get()
positions_get(symbol="SYMBOL")
positions_get(group="GROUP")
positions_get(ticket=TICKET)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Filter by exact symbol name (e.g. `"EURUSD"`). Overrides `ticket`. |
| `group` | str | Filter by symbol pattern with wildcards (`*`) and negation (`!`). |
| `ticket` | int | Filter by position ticket number. |

### Return Value

Tuple of named tuples, one per position. Returns `None` on error (not empty tuple). Use `last_error()` for error details.

> **Always check for `None`**, not just falsy — an empty tuple `()` means no open positions (valid), `None` means an error.

### Position Fields

| Field | Type | Description |
|-------|------|-------------|
| `ticket` | int | Position ticket |
| `time` | int | Opening time (Unix timestamp, seconds) |
| `time_msc` | int | Opening time (milliseconds) |
| `time_update` | int | Last modification time |
| `time_update_msc` | int | Last modification time (milliseconds) |
| `type` | int | Position type: **0=buy, 1=sell** |
| `magic` | int | Expert Advisor magic number |
| `identifier` | int | Position identifier |
| `reason` | int | Open reason |
| `volume` | float | Position size in lots |
| `price_open` | float | Open price |
| `sl` | float | Stop loss price (0 if not set) |
| `tp` | float | Take profit price (0 if not set) |
| `price_current` | float | Current market price |
| `swap` | float | Accumulated swap |
| `profit` | float | Current floating profit/loss |
| `symbol` | str | Symbol name |
| `comment` | str | Position comment |
| `external_id` | str | External position identifier |

### Group Filter Syntax

- `"*USD*"` — symbols containing "USD"
- `"EUR*,GBP*"` — symbols starting with EUR or GBP
- `"*,!EUR*"` — all symbols except those starting with EUR
- Conditions are applied left-to-right; include before exclude.

### Example

```python
import MetaTrader5 as mt5
import pandas as pd

if not mt5.initialize():
    quit()

# All open positions
positions = mt5.positions_get()
if positions is None:
    print("Error:", mt5.last_error())
elif len(positions) == 0:
    print("No open positions")
else:
    df = pd.DataFrame(list(positions), columns=positions[0]._asdict().keys())
    df['time'] = pd.to_datetime(df['time'], unit='s')
    print(df[['ticket','symbol','type','volume','price_open','price_current','profit']])

# Positions on specific symbol
usdjpy = mt5.positions_get(symbol="USDJPY")

# All USD positions
usd_pos = mt5.positions_get(group="*USD*")

# Single position by ticket
pos = mt5.positions_get(ticket=123456789)

mt5.shutdown()
```

### Normalization (as used in this project)

```python
def normalize_position(pos) -> dict:
    return {
        "ticket":        pos.ticket,
        "symbol":        pos.symbol,
        "type":          "buy" if pos.type == 0 else "sell",
        "volume":        pos.volume,
        "open_price":    pos.price_open,
        "current_price": pos.price_current,
        "sl":            pos.sl or None,   # 0 → None
        "tp":            pos.tp or None,
        "profit":        pos.profit,
        "swap":          pos.swap,
        "open_time":     datetime.fromtimestamp(pos.time, UTC).isoformat(),
    }
```

---

## positions_total()

Get the number of open positions.

```python
positions_total()
```

Returns an `int`. Returns `-1` on error.
