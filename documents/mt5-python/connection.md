# MT5 Python — Connection Functions

Source: https://www.mql5.com/en/docs/python_metatrader5

---

## initialize()

Establish connection with MetaTrader 5 terminal.

```python
initialize()
initialize(path)
initialize(path, login=LOGIN, password="PASSWORD", server="SERVER", timeout=TIMEOUT, portable=False)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | str | No | Path to `metatrader.exe` or `metatrader64.exe`. Omit to auto-detect. |
| `login` | int | No (named) | Trading account number. Uses last account if omitted. |
| `password` | str | No (named) | Trading account password. Uses saved terminal password if omitted. |
| `server` | str | No (named) | Trade server name as configured in terminal. Uses saved server if omitted. |
| `timeout` | int | No (named) | Connection timeout in milliseconds. Default: 60,000 (60 sec). |
| `portable` | bool | No (named) | Enable portable mode. Default: False. |

### Return Value

`True` on success, `False` on failure. Call `last_error()` for details on failure.

### Notes

- **Slow call** — launches the MT5 terminal if not already running. Call once per session, not per request.
- **COM thread binding** — binds to the OS thread that called it. All subsequent MT5 calls **must** be on the same thread. Use `ThreadPoolExecutor(max_workers=1)`.
- You can pass `login`/`password`/`server` here or call `login()` separately after `initialize()`.

### Example

```python
import MetaTrader5 as mt5

if not mt5.initialize(login=25115284, server="MetaQuotes-Demo", password="4zatlbqx"):
    print("initialize() failed, error code =", mt5.last_error())
    quit()

print(mt5.terminal_info())
print(mt5.version())

mt5.shutdown()
```

---

## login()

Connect to a trading account (without re-initializing the terminal).

```python
login(login, password="PASSWORD", server="SERVER", timeout=TIMEOUT)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `login` | int | Yes | Trading account number. |
| `password` | str | No (named) | Account password. Uses saved terminal password if omitted. |
| `server` | str | No (named) | Trade server name. Uses last server if omitted. |
| `timeout` | int | No (named) | Connection timeout ms. Default: 60,000. |

### Return Value

`True` on success, `False` on failure.

### Notes

- Use after `initialize()` to switch accounts **without** disconnecting the terminal.
- Useful when you want to separate terminal startup from account authentication.

### Example

```python
import MetaTrader5 as mt5

if not mt5.initialize():
    print("initialize() failed, error code =", mt5.last_error())
    quit()

# Switch to a specific account
account = 25115284
if mt5.login(account, password="gqrtz0lbdm"):
    print("Connected to account #{}".format(account))
    print(mt5.account_info())
else:
    print("Login failed, error code:", mt5.last_error())

mt5.shutdown()
```

---

## shutdown()

Close the previously established connection to the MetaTrader 5 terminal.

```python
shutdown()
```

### Parameters

None.

### Return Value

`None`.

### Notes

- Always call in a `finally` block to guarantee cleanup even if an exception occurs.
- After `shutdown()`, the terminal process may keep running but the Python IPC channel is closed.

### Example (recommended pattern)

```python
import MetaTrader5 as mt5

if not mt5.initialize(login=..., password=..., server=...):
    raise ConnectionError(f"MT5 init failed: {mt5.last_error()}")

try:
    while True:
        info = mt5.account_info()
        # ... process data ...
        time.sleep(5)
finally:
    mt5.shutdown()  # always runs, even on exception or cancellation
```
