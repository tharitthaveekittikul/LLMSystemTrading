# MT5 Python — Market Data

Source: https://www.mql5.com/en/docs/python_metatrader5

---

## symbol_select()

Add or remove a symbol from MarketWatch.

```python
symbol_select(symbol)         # add to MarketWatch
symbol_select(symbol, True)   # add to MarketWatch (explicit)
symbol_select(symbol, False)  # remove from MarketWatch
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Financial instrument name. Required. |
| `enable` | bool | `True` = add (default), `False` = remove. |

### Return Value

`True` on success, `False` on failure.

### Notes

- **Must call before `symbol_info_tick()`** if the symbol is not already in MarketWatch.
- A symbol cannot be removed if there are open charts or positions on it.
- Only needs to be called once per terminal session — symbols stay in MarketWatch until removed.

### Example

```python
if not mt5.symbol_select("EURUSD", True):
    print("Failed to select EURUSD:", mt5.last_error())
    quit()

tick = mt5.symbol_info_tick("EURUSD")
```

---

## symbol_info_tick()

Get the last tick (bid/ask) for a symbol.

```python
symbol_info_tick(symbol)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Financial instrument name. Required. |

### Return Value

Named tuple with tick data, or `None` on error.

### Tick Fields

| Field | Type | Description |
|-------|------|-------------|
| `time` | int | Tick time (Unix timestamp, seconds) |
| `bid` | float | Bid price |
| `ask` | float | Ask price |
| `last` | float | Last traded price |
| `volume` | int | Tick volume |
| `time_msc` | int | Tick time (milliseconds) |
| `flags` | int | Tick flags |
| `volume_real` | float | Real tick volume |

### Example

```python
import MetaTrader5 as mt5

if not mt5.initialize():
    quit()

# Ensure symbol is in MarketWatch first
mt5.symbol_select("GBPUSD", True)

tick = mt5.symbol_info_tick("GBPUSD")
if tick:
    print(f"GBPUSD bid={tick.bid} ask={tick.ask}")
    print(f"Spread: {(tick.ask - tick.bid):.5f}")
else:
    print("Error:", mt5.last_error())

mt5.shutdown()
```

---

## copy_rates_from_pos()

Get OHLCV bars starting from a bar index (0 = current/most recent).

```python
copy_rates_from_pos(symbol, timeframe, start_pos, count)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Instrument name (e.g. `"EURUSD"`). Required. |
| `timeframe` | int | Timeframe constant (see below). Required. |
| `start_pos` | int | Starting bar index. 0 = current bar. Required. |
| `count` | int | Number of bars to retrieve. Required. |

### Timeframe Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `mt5.TIMEFRAME_M1` | 1 | 1 minute |
| `mt5.TIMEFRAME_M5` | 5 | 5 minutes |
| `mt5.TIMEFRAME_M15` | 15 | 15 minutes |
| `mt5.TIMEFRAME_M30` | 30 | 30 minutes |
| `mt5.TIMEFRAME_H1` | 16385 | 1 hour |
| `mt5.TIMEFRAME_H4` | 16388 | 4 hours |
| `mt5.TIMEFRAME_D1` | 16408 | 1 day |
| `mt5.TIMEFRAME_W1` | 32769 | 1 week |
| `mt5.TIMEFRAME_MN1` | 49153 | 1 month |

### Return Value

NumPy structured array with columns: `time`, `open`, `high`, `low`, `close`, `tick_volume`, `spread`, `real_volume`. Returns `None` on error.

### Notes

- Terminal only provides bars within the user's chart history limit (set by "Max. bars in chart").
- `time` values are Unix timestamps in seconds — convert with `pd.to_datetime(df['time'], unit='s')`.

### Example

```python
import MetaTrader5 as mt5
import pandas as pd

if not mt5.initialize():
    quit()

# Get last 100 M15 bars for EURUSD
rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M15, 0, 100)

mt5.shutdown()

if rates is not None:
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    print(df.tail())
```
