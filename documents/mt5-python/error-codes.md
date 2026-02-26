# MT5 Python — Error Codes

Source: https://www.mql5.com/en/docs/python_metatrader5/mt5lasterror_py

---

## last_error()

Return the last error code and description from the MT5 Python library.

```python
last_error()
```

### Return Value

Tuple `(code: int, description: str)`.

### Error Codes

| Constant | Code | Description |
|----------|------|-------------|
| `RES_S_OK` | 1 | Generic success |
| `RES_E_FAIL` | -1 | Generic failure |
| `RES_E_INVALID_PARAMS` | **-2** | **Invalid arguments/parameters** (e.g. bad `path`) |
| `RES_E_NO_MEMORY` | -3 | No memory |
| `RES_E_NOT_FOUND` | -4 | No history / not found |
| `RES_E_INVALID_VERSION` | -5 | Invalid version |
| `RES_E_AUTH_FAILED` | **-6** | **Authorization failed** (wrong login/password/server) |
| `RES_E_UNSUPPORTED` | -7 | Unsupported method |
| `RES_E_AUTO_TRADING_DISABLED` | -8 | Auto-trading disabled in terminal |
| `RES_E_INTERNAL_FAIL` | -10000 | Internal IPC general error |
| `RES_E_INTERNAL_FAIL_SEND` | -10001 | Internal IPC send failed |
| `RES_E_INTERNAL_FAIL_RECEIVE` | -10002 | Internal IPC receive failed |
| `RES_E_INTERNAL_FAIL_INIT` | -10003 | Internal IPC initialization failed |
| `RES_E_INTERNAL_FAIL_CONNECT` | -10003 | Internal IPC — no IPC channel |
| `RES_E_INTERNAL_FAIL_TIMEOUT` | -10005 | Internal IPC timeout |

### Common Error Scenarios

| Symptom | Likely Code | Cause |
|---------|-------------|-------|
| `initialize()` returns False | -2 | Wrong `path` to terminal64.exe |
| `initialize()` returns False | -6 | Wrong login/password/server |
| `initialize()` returns False | -10003 | Terminal not running or IPC blocked |
| `account_info()` returns None | -6 | Not logged in |
| `positions_get()` returns None | -4 | No positions found (may be normal) |

### Example

```python
import MetaTrader5 as mt5

if not mt5.initialize(login=12345, password="wrong", server="MyBroker-Server"):
    code, msg = mt5.last_error()
    print(f"initialize() failed: code={code} msg={msg}")
    # e.g. code=-6 msg='Authorization failed'
    quit()
```

### In this project (`bridge.py`)

```python
async def connect(self) -> bool:
    ok = await self._run(mt5.initialize, ...)
    if not ok:
        code, msg = await self.get_last_error()
        # code=-2 means bad path, code=-6 means wrong credentials
        logger.error("MT5 connect failed | code=%s msg=%s", code, msg)
    return ok
```

---

## Trade Return Codes (order_send result)

These are returned in `result.retcode`, NOT from `last_error()`.

| Code | Constant | Description |
|------|----------|-------------|
| **10009** | `TRADE_RETCODE_DONE` | **Success** |
| 10004 | `TRADE_RETCODE_REQUOTE` | Requote |
| 10006 | `TRADE_RETCODE_REJECT` | Request rejected |
| 10007 | `TRADE_RETCODE_CANCEL` | Request cancelled |
| 10008 | `TRADE_RETCODE_PLACED` | Order placed |
| 10010 | `TRADE_RETCODE_DONE_PARTIAL` | Partial fill |
| 10011 | `TRADE_RETCODE_ERROR` | Processing error |
| 10012 | `TRADE_RETCODE_TIMEOUT` | Request timed out |
| 10013 | `TRADE_RETCODE_INVALID` | Invalid request |
| 10014 | `TRADE_RETCODE_INVALID_VOLUME` | Invalid volume |
| 10015 | `TRADE_RETCODE_INVALID_PRICE` | Invalid price |
| 10016 | `TRADE_RETCODE_INVALID_STOPS` | Invalid stops |
| 10018 | `TRADE_RETCODE_MARKET_CLOSED` | Market closed |
| 10019 | `TRADE_RETCODE_NO_MONEY` | Insufficient funds |
| 10020 | `TRADE_RETCODE_PRICE_CHANGED` | Price changed |
| 10021 | `TRADE_RETCODE_PRICE_OFF` | No quotes |
| 10030 | `TRADE_RETCODE_INVALID_FILL` | Invalid fill type |
