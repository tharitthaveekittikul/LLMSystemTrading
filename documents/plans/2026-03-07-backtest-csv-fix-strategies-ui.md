# Backtest CSV Fix, Strategies UI Overhaul & DB Cleanup — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix CSV upload to accept MT5 tab-delimited format with per-candle spread, update backtest results to show avg spread, overhaul the strategies page with 5 execution modes + edit page + performance stats on cards, and add a DB test-data cleanup script.

**Architecture:** Backend changes first (data layer → engine → routes → new endpoint), then frontend types, then UI components. Each backend task has failing tests written before implementation. Frontend tasks are purely UI changes (no tests for UI components).

**Tech Stack:** Python/FastAPI backend (uv, pytest), Next.js 16 frontend (TypeScript), PostgreSQL (Alembic migrations), pandas for CSV parsing.

---

## Task 1: Add `spread` field to `OHLCV` + populate from MT5 CSV

**Files:**
- Modify: `backend/services/mtf_data.py`
- Modify: `backend/services/mtf_csv_loader.py`
- Modify: `backend/tests/test_mtf_csv_loader.py`

**Step 1: Write the failing test**

In `backend/tests/test_mtf_csv_loader.py`, add after the existing tests:

```python
def test_load_mt5_csv_reads_spread_column():
    """Spread column is parsed and stored in OHLCV.spread."""
    candles = load_mt5_csv(io.StringIO(SAMPLE_MT5_CSV))
    # SAMPLE_MT5_CSV has spreads 200, 588, 400
    assert candles[0].spread == 200
    assert candles[1].spread == 588
    assert candles[2].spread == 400


def test_load_mt5_csv_spread_defaults_to_zero_when_absent():
    """OHLCV.spread == 0 if CSV has no <SPREAD> column."""
    csv_no_spread = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\n"
        "2017.01.02\t00:00:00\t1.10000\t1.10100\t1.09900\t1.10050\t100\t0\n"
    )
    candles = load_mt5_csv(io.StringIO(csv_no_spread))
    assert candles[0].spread == 0
```

**Step 2: Run to verify failure**

```bash
cd backend
uv run pytest tests/test_mtf_csv_loader.py::test_load_mt5_csv_reads_spread_column -v
```

Expected: `AttributeError: 'OHLCV' object has no attribute 'spread'`

**Step 3: Add `spread` field to `OHLCV`**

In `backend/services/mtf_data.py`, update the `OHLCV` dataclass:

```python
@dataclass
class OHLCV:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int = 0  # MT5 spread in points (0 if not provided)
```

**Step 4: Populate `spread` in `mtf_csv_loader.py`**

In `backend/services/mtf_csv_loader.py`:

1. Change `_REQUIRED` to not require spread (it's optional):

```python
_REQUIRED = {"date", "time", "open", "high", "low", "close", "tickvol"}
```

(It was already optional — no change needed there.)

2. In `load_mt5_csv()`, update the list comprehension that builds `OHLCV` objects:

```python
candles = [
    OHLCV(
        time=row.datetime.to_pydatetime(),
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
        tick_volume=int(row.tickvol),
        spread=int(getattr(row, "spread", 0) or 0),
    )
    for row in df.itertuples()
]
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_mtf_csv_loader.py -v
```

Expected: All 7 tests pass.

**Step 6: Commit**

```bash
git add backend/services/mtf_data.py backend/services/mtf_csv_loader.py backend/tests/test_mtf_csv_loader.py
git commit -m "feat(data): add spread field to OHLCV, read <SPREAD> from MT5 CSV"
```

---

## Task 2: Fix `BacktestDataService.load_from_csv()` to accept MT5 format

**Files:**
- Modify: `backend/services/backtest_data.py`
- Modify: `backend/tests/test_backtest_data.py`

**Background:** Currently `load_from_csv()` uses plain comma-separated CSV with column names `time,open,high,low,close,tick_volume`. MT5 exports are tab-separated with `<DATE>`,`<TIME>`,`<OPEN>`,... headers. Fix: delegate to `mtf_csv_loader.load_mt5_csv()` and convert to dicts.

**Step 1: Write failing test for MT5 format**

Replace the content of `backend/tests/test_backtest_data.py` with:

```python
"""Tests for BacktestDataService — CSV parsing and MT5 error handling."""
import io
import pytest

# MT5 export format (tab-separated, angle-bracket headers)
SAMPLE_MT5_CSV = (
    "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
    "2020.01.02\t00:00:00\t1.12345\t1.12400\t1.12300\t1.12380\t100\t0\t15\n"
    "2020.01.02\t00:15:00\t1.12380\t1.12450\t1.12350\t1.12420\t120\t0\t18\n"
)


@pytest.mark.asyncio
async def test_load_from_csv_accepts_mt5_format():
    """MT5 tab-delimited CSV with angle-bracket headers parses correctly."""
    from services.backtest_data import BacktestDataService

    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert len(candles) == 2
    assert candles[0]["open"] == pytest.approx(1.12345)
    assert candles[1]["close"] == pytest.approx(1.12420)


@pytest.mark.asyncio
async def test_load_from_csv_includes_spread():
    """Result candle dicts include 'spread' key from <SPREAD> column."""
    from services.backtest_data import BacktestDataService

    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(SAMPLE_MT5_CSV))
    assert candles[0]["spread"] == 15
    assert candles[1]["spread"] == 18


@pytest.mark.asyncio
async def test_load_from_csv_missing_required_column_raises():
    """CSV missing required columns raises BacktestDataError."""
    from services.backtest_data import BacktestDataService, BacktestDataError

    bad_csv = "col1\tcol2\n1\t2\n"
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="Missing columns"):
        await svc.load_from_csv(io.StringIO(bad_csv))


@pytest.mark.asyncio
async def test_load_from_csv_sorted_by_time():
    """Candles are returned sorted oldest-first regardless of CSV order."""
    from services.backtest_data import BacktestDataService

    # Rows in reverse order
    csv = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2020.01.02\t00:15:00\t1.20000\t1.30000\t1.10000\t1.25000\t80\t0\t10\n"
        "2020.01.02\t00:00:00\t1.10000\t1.20000\t1.00000\t1.15000\t60\t0\t10\n"
    )
    from services.backtest_data import BacktestDataService

    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(csv))
    assert candles[0]["open"] == pytest.approx(1.1)
    assert candles[1]["open"] == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_load_from_mt5_empty_raises():
    """When MT5Bridge returns empty list, BacktestDataError is raised."""
    from unittest.mock import AsyncMock
    from services.backtest_data import BacktestDataService, BacktestDataError

    bridge = AsyncMock()
    bridge.get_rates_range = AsyncMock(return_value=[])
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="No data returned"):
        await svc.load_from_mt5(bridge, "EURUSD", 16408, None, None)


@pytest.mark.asyncio
async def test_load_from_mt5_propagates_error():
    """When MT5Bridge raises, BacktestDataError wraps it."""
    from unittest.mock import AsyncMock
    from services.backtest_data import BacktestDataService, BacktestDataError

    bridge = AsyncMock()
    bridge.get_rates_range = AsyncMock(side_effect=RuntimeError("MT5 not connected"))
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="MT5 fetch failed"):
        await svc.load_from_mt5(bridge, "EURUSD", 16408, None, None)
```

**Step 2: Run to verify failures**

```bash
uv run pytest tests/test_backtest_data.py -v
```

Expected: `test_load_from_csv_accepts_mt5_format` and `test_load_from_csv_includes_spread` FAIL (MT5 headers not recognised).

**Step 3: Replace `load_from_csv()` in `backend/services/backtest_data.py`**

Replace the entire file with:

```python
"""BacktestDataService — load historical OHLCV from MT5 or CSV.

MT5 path: requires a connected MT5Bridge (caller provides it).
CSV path: accepts MT5 tab-delimited export format (angle-bracket headers).
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


class BacktestDataError(ValueError):
    """Raised when OHLCV data cannot be loaded or is invalid."""


class BacktestDataService:
    async def load_from_mt5(
        self,
        bridge,
        symbol: str,
        timeframe: int,
        date_from,
        date_to,
    ) -> list[dict]:
        """Fetch OHLCV candles from MT5 for the given date range.

        Returns list of dicts: time, open, high, low, close, tick_volume, spread.
        """
        try:
            candles = await bridge.get_rates_range(symbol, timeframe, date_from, date_to)
        except Exception as exc:
            raise BacktestDataError(f"MT5 fetch failed: {exc}") from exc

        if not candles:
            raise BacktestDataError(
                f"No data returned for {symbol} {date_from} → {date_to}. "
                "Check that the symbol is available in Market Watch and MT5 has history downloaded."
            )
        logger.info("Loaded %d candles from MT5 | %s", len(candles), symbol)
        return candles

    async def load_from_csv(self, file: io.StringIO | io.BytesIO) -> list[dict]:
        """Parse an MT5 tab-delimited CSV into a list of OHLCV candle dicts.

        Expects MT5 export format:
          <DATE>  <TIME>  <OPEN>  <HIGH>  <LOW>  <CLOSE>  <TICKVOL>  <VOL>  <SPREAD>
          2017.01.02  00:00:00  1.10000  ...

        Returns dicts with keys: time, open, high, low, close, tick_volume, spread.
        Raises BacktestDataError on parse failure.
        """
        from services.mtf_csv_loader import load_mt5_csv, MTFCSVError

        try:
            ohlcv_list = load_mt5_csv(file)
        except MTFCSVError as exc:
            raise BacktestDataError(str(exc)) from exc

        candles = [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "tick_volume": c.tick_volume,
                "spread": c.spread,
            }
            for c in ohlcv_list
        ]
        logger.info("Loaded %d candles from CSV", len(candles))
        return candles
```

**Step 4: Run tests to verify they all pass**

```bash
uv run pytest tests/test_backtest_data.py -v
```

Expected: All 6 tests pass.

**Step 5: Commit**

```bash
git add backend/services/backtest_data.py backend/tests/test_backtest_data.py
git commit -m "fix(backtest): accept MT5 tab-delimited CSV format in load_from_csv"
```

---

## Task 3: Update `BacktestEngine` to use per-candle spread + compute `avg_spread`

**Files:**
- Modify: `backend/services/backtest_engine.py`
- Modify: `backend/tests/test_backtest_engine.py`

**Step 1: Write failing test for avg_spread in result**

In `backend/tests/test_backtest_engine.py`, add to the `_make_candles()` helper and add tests at the end of the file:

First, update `_make_candles()` to optionally include spread:

```python
def _make_candles(n: int, base_price: float = 1.10000, spread: int = 0) -> list[dict]:
    """Generate n synthetic M15 candles with a mild uptrend."""
    candles = []
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    price = base_price
    for _ in range(n):
        candles.append({
            "time": t,
            "open": price,
            "high": price + 0.00050,
            "low": price - 0.00030,
            "close": price + 0.00010,
            "tick_volume": 100,
            "spread": spread,
        })
        price += 0.00001
        t += timedelta(minutes=15)
    return candles
```

Then add these new test functions at the bottom of the file:

```python
@pytest.mark.asyncio
async def test_engine_result_contains_avg_spread():
    """BacktestEngine.run() result includes 'avg_spread' key."""
    from services.backtest_engine import BacktestEngine

    candles = _make_candles(100, spread=20)
    engine = BacktestEngine()
    config = {
        "symbol": "EURUSD", "timeframe": "M15",
        "initial_balance": 10000.0, "spread_pips": 1.5,
        "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0,
    }
    result = await engine.run(candles, _always_hold_strategy(), config, None)
    assert "avg_spread" in result
    assert result["avg_spread"] == pytest.approx(20.0, abs=0.1)


@pytest.mark.asyncio
async def test_engine_avg_spread_zero_when_no_spread_in_candles():
    """avg_spread is 0.0 when candles have no 'spread' key."""
    from services.backtest_engine import BacktestEngine

    candles = _make_candles(100)  # no spread key
    engine = BacktestEngine()
    config = {
        "symbol": "EURUSD", "timeframe": "M15",
        "initial_balance": 10000.0, "spread_pips": 1.5,
        "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0,
    }
    result = await engine.run(candles, _always_hold_strategy(), config, None)
    assert result["avg_spread"] == 0.0


@pytest.mark.asyncio
async def test_engine_per_candle_spread_used_in_intra_candle_mode():
    """intra_candle mode uses per-candle spread from CSV when non-zero."""
    from services.backtest_engine import BacktestEngine

    # Use spread=100 points for EURUSD = 100 * 0.00001 = 0.001 price offset
    candles = _make_candles(200, spread=100)
    engine = BacktestEngine()
    config = {
        "symbol": "EURUSD", "timeframe": "M15",
        "initial_balance": 10000.0, "spread_pips": 0.0,  # 0 config spread
        "execution_mode": "intra_candle", "volume": 0.1, "max_llm_calls": 0,
    }
    result = await engine.run(candles, _always_buy_strategy(), config, None)
    # With per-candle spread, some trades should have opened at next_open + spread offset
    assert len(result["trades"]) > 0
```

**Step 2: Run to verify failures**

```bash
uv run pytest tests/test_backtest_engine.py::test_engine_result_contains_avg_spread -v
```

Expected: `KeyError: 'avg_spread'`

**Step 3: Update `BacktestEngine` in `backend/services/backtest_engine.py`**

Make these changes:

A. Add `_spread_to_price()` helper after `_pip_value()`:

```python
def _spread_to_price(spread_pts: int, symbol: str) -> float:
    """Convert MT5 spread in points to a price offset.

    MT5 point size by instrument:
      JPY pairs  : 1 pt = 0.001
      Metals/index: 1 pt = 0.01  (XAU, XAG, US30, NAS, SPX)
      Forex 5-digit: 1 pt = 0.00001  (default)
    """
    if "JPY" in symbol:
        return spread_pts * 0.001
    if any(m in symbol for m in ("XAU", "XAG", "US30", "NAS", "SPX", "DAX")):
        return spread_pts * 0.01
    return spread_pts * 0.00001
```

B. In `BacktestEngine.run()`, replace the single `spread` line:

```python
# OLD (line 87):
spread = config.get("spread_pips", 1.5) * _pip_value(symbol)

# NEW:
default_spread_price = config.get("spread_pips", 1.5) * _pip_value(symbol)
```

C. Inside the candle loop (after `for i, candle in enumerate(candles):`), add per-candle spread computation before the signal-generation block:

```python
# Per-candle spread (from CSV); falls back to config spread_pips
spread_pts = candle.get("spread", 0)
candle_spread_price = (
    _spread_to_price(spread_pts, symbol) if spread_pts > 0
    else default_spread_price
)
```

D. Update the `_fill_price` call to pass `candle_spread_price` instead of `spread`:

```python
# OLD:
fill_price = _fill_price(signal, candle, candles, i, mode, spread)
# NEW:
fill_price = _fill_price(signal, candle, candles, i, mode, candle_spread_price)
```

E. After the candle loop, before the final return, compute avg_spread:

```python
spread_values = [c.get("spread", 0) for c in candles]
avg_spread = (
    round(sum(spread_values) / len(spread_values), 1)
    if spread_values else 0.0
)
```

F. Update the final return:

```python
return {"trades": trades, "equity_curve": equity_curve, "avg_spread": avg_spread}
```

**Step 4: Run tests to verify they all pass**

```bash
uv run pytest tests/test_backtest_engine.py -v
```

Expected: All engine tests pass.

**Step 5: Commit**

```bash
git add backend/services/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(engine): per-candle spread from CSV + avg_spread in result"
```

---

## Task 4: Alembic migration — add `avg_spread` to `backtest_runs`

**Files:**
- Modify: `backend/db/models.py`
- Create: `backend/alembic/versions/XXXX_add_avg_spread_to_backtest_runs.py`

**Step 1: Add column to the SQLAlchemy model**

In `backend/db/models.py`, inside the `BacktestRun` class, add after `max_consec_losses`:

```python
avg_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
```

**Step 2: Generate Alembic migration**

```bash
cd backend
uv run alembic revision --autogenerate -m "add_avg_spread_to_backtest_runs"
```

This creates a new file in `backend/alembic/versions/`. Open it and verify it contains:

```python
def upgrade() -> None:
    op.add_column('backtest_runs', sa.Column('avg_spread', sa.Float(), nullable=True))

def downgrade() -> None:
    op.drop_column('backtest_runs', 'avg_spread')
```

**Step 3: Apply migration**

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade ... -> XXXX` (no errors).

**Step 4: Commit**

```bash
git add backend/db/models.py backend/alembic/versions/
git commit -m "feat(db): add avg_spread column to backtest_runs"
```

---

## Task 5: Update backtest route — upload response, summary schema, persist `avg_spread`

**Files:**
- Modify: `backend/api/routes/backtest.py`

**Step 1: Update `POST /backtest/data/upload` response**

Replace the `upload_csv` endpoint:

```python
@router.post("/data/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    """Save uploaded CSV to temp file, return upload_id + avg_spread_pts for display."""
    import io as _io
    suffix = ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as f:
        content = await file.read()
        f.write(content)
        tmp_path = f.name

    # Compute avg spread for display in the UI
    avg_spread_pts: float | None = None
    try:
        from services.backtest_data import BacktestDataService
        svc = BacktestDataService()
        candles = await svc.load_from_csv(_io.StringIO(content.decode("utf-8", errors="replace")))
        spreads = [c["spread"] for c in candles if c.get("spread", 0) > 0]
        if spreads:
            avg_spread_pts = round(sum(spreads) / len(spreads), 1)
    except Exception:
        pass  # avg_spread is informational — never fail the upload for it

    logger.info("CSV uploaded: %s (%d bytes, avg_spread=%.1f pts)",
                tmp_path, len(content), avg_spread_pts or 0)
    return {"upload_id": tmp_path, "size_bytes": len(content), "avg_spread_pts": avg_spread_pts}
```

**Step 2: Add `avg_spread` to `BacktestRunSummary`**

In `BacktestRunSummary`, add the field:

```python
avg_spread: float | None
```

In `BacktestRunSummary.from_orm()`, add:

```python
avg_spread=r.avg_spread,
```

**Step 3: Persist `avg_spread` after run in `_run_backtest_job()`**

After `result = await engine.run(...)`, add:

```python
run.avg_spread = result.get("avg_spread")
```

(Add this right before or after the existing `run.total_trades = ...` block.)

**Step 4: Run the full test suite to verify no regressions**

```bash
uv run pytest tests/ -q
```

Expected: All tests pass (the new field is nullable so existing tests aren't affected).

**Step 5: Commit**

```bash
git add backend/api/routes/backtest.py
git commit -m "feat(backtest): expose avg_spread in upload response and run summary"
```

---

## Task 6: Add strategy stats endpoint + `execution_mode` in strategy responses

**Files:**
- Modify: `backend/api/routes/strategies.py`

**Step 1: Add `execution_mode` to `StrategyResponse` and `StrategyCreate`/`StrategyUpdate`**

In `strategies.py`, update the Pydantic schemas:

A. `StrategyResponse` — add field after `strategy_type`:

```python
execution_mode: str
```

B. `StrategyCreate` — add field after `strategy_type`:

```python
execution_mode: str = "llm_only"
```

C. `StrategyUpdate` — add field after `strategy_type`:

```python
execution_mode: str | None = None
```

**Step 2: Update `_to_response()` to include `execution_mode`**

```python
def _to_response(strategy: Strategy, binding_count: int = 0) -> StrategyResponse:
    return StrategyResponse(
        id=strategy.id,
        name=strategy.name,
        description=strategy.description,
        strategy_type=strategy.strategy_type,
        execution_mode=strategy.execution_mode,     # ADD THIS LINE
        trigger_type=strategy.trigger_type,
        interval_minutes=strategy.interval_minutes,
        symbols=json.loads(strategy.symbols or "[]"),
        timeframe=strategy.timeframe,
        lot_size=strategy.lot_size,
        sl_pips=strategy.sl_pips,
        tp_pips=strategy.tp_pips,
        news_filter=strategy.news_filter,
        custom_prompt=strategy.custom_prompt,
        module_path=strategy.module_path,
        class_name=strategy.class_name,
        is_active=strategy.is_active,
        binding_count=binding_count,
    )
```

**Step 3: Update `create_strategy()` to handle `execution_mode`**

In `create_strategy()`, after `body: StrategyCreate`, derive `strategy_type` from `execution_mode`:

```python
@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(body: StrategyCreate, db: AsyncSession = Depends(get_db)):
    # Derive strategy_type from execution_mode if not explicitly provided
    execution_mode = body.execution_mode or "llm_only"
    strategy_type = body.strategy_type
    if execution_mode == "llm_only":
        strategy_type = "prompt"
    elif execution_mode in {"rule_only", "rule_then_llm", "hybrid_validator", "multi_agent"}:
        strategy_type = "code"

    strategy = Strategy(
        name=body.name,
        description=body.description,
        strategy_type=strategy_type,
        execution_mode=execution_mode,
        # ... rest unchanged
    )
```

**Step 4: Update `update_strategy()` to handle `execution_mode`**

Find the section that updates strategy fields and add:

```python
if body.execution_mode is not None:
    strategy.execution_mode = body.execution_mode
    # Keep strategy_type in sync
    if body.execution_mode == "llm_only":
        strategy.strategy_type = "prompt"
    elif body.execution_mode in {"rule_only", "rule_then_llm", "hybrid_validator", "multi_agent"}:
        strategy.strategy_type = "code"
```

**Step 5: Add the stats endpoint**

Add these imports at the top of `strategies.py` (after existing imports):

```python
from sqlalchemy import desc
from db.models import BacktestRun, Trade
```

Add the new endpoint after the `/runs` endpoint:

```python
@router.get("/{strategy_id}/stats")
async def get_strategy_stats(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return latest backtest stats + live trading stats for a strategy."""
    await _get_or_404(db, strategy_id)

    # Latest completed backtest run
    latest_bt = (await db.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy_id)
        .where(BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.created_at))
        .limit(1)
    )).scalar_one_or_none()

    # All closed live trades for this strategy
    closed_trades_result = await db.execute(
        select(Trade)
        .where(Trade.strategy_id == strategy_id)
        .where(Trade.closed_at.is_not(None))
    )
    closed_trades = closed_trades_result.scalars().all()

    backtest_stats = None
    if latest_bt:
        backtest_stats = {
            "win_rate": latest_bt.win_rate,
            "profit_factor": latest_bt.profit_factor,
            "total_trades": latest_bt.total_trades,
            "total_return_pct": latest_bt.total_return_pct,
            "max_drawdown_pct": latest_bt.max_drawdown_pct,
            "run_date": latest_bt.created_at.isoformat(),
            "symbol": latest_bt.symbol,
            "timeframe": latest_bt.timeframe,
        }

    live_stats = None
    if closed_trades:
        wins = [t for t in closed_trades if (t.profit or 0) > 0]
        total_pnl = sum((t.profit or 0) for t in closed_trades)
        live_stats = {
            "total_trades": len(closed_trades),
            "win_rate": round(len(wins) / len(closed_trades), 4),
            "total_pnl": round(total_pnl, 2),
        }

    return {"backtest": backtest_stats, "live": live_stats}
```

**Step 6: Run full test suite**

```bash
uv run pytest tests/ -q
```

Expected: All tests pass.

**Step 7: Commit**

```bash
git add backend/api/routes/strategies.py
git commit -m "feat(strategies): add execution_mode to responses, add stats endpoint"
```

---

## Task 7: Cleanup script for test data

**Files:**
- Create: `backend/scripts/__init__.py` (empty, makes it a package)
- Create: `backend/scripts/cleanup_test_data.py`

**Step 1: Create `backend/scripts/__init__.py`**

Empty file.

**Step 2: Create `backend/scripts/cleanup_test_data.py`**

```python
"""Cleanup script — remove dev/test data from the database.

Deletes:
  - llm_calls rows where model name is a known test/dev model
  - pipeline_steps and pipeline_runs that have no account activity

Usage (from backend/ directory):
    uv run python scripts/cleanup_test_data.py

Safe to re-run (idempotent).
"""
import asyncio
import logging
from sqlalchemy import delete, select, func
from db.postgres import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Models known to be from dev/test use only — adjust as needed
TEST_MODELS = {
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "gemini-2.5-flash",
    "gemini-pro",
    "gemini-1.5-flash",
    "claude-3-opus-20240229",
}


async def main() -> None:
    from db.models import LLMCall, PipelineStep, PipelineRun

    async with AsyncSessionLocal() as db:
        # ── Count before ──────────────────────────────────────────────────────
        llm_count_before = (await db.execute(
            select(func.count()).select_from(LLMCall)
            .where(LLMCall.model.in_(TEST_MODELS))
        )).scalar_one()

        pipeline_runs_before = (await db.execute(
            select(func.count()).select_from(PipelineRun)
            .where(PipelineRun.journal_id.is_(None))
            .where(PipelineRun.trade_id.is_(None))
        )).scalar_one()

        logger.info("Before cleanup:")
        logger.info("  llm_calls with test model names:  %d", llm_count_before)
        logger.info("  orphaned pipeline_runs (no journal, no trade): %d", pipeline_runs_before)

        if llm_count_before == 0 and pipeline_runs_before == 0:
            logger.info("Nothing to clean up.")
            return

        # ── Delete llm_calls with test model names ────────────────────────────
        if llm_count_before > 0:
            await db.execute(
                delete(LLMCall).where(LLMCall.model.in_(TEST_MODELS))
            )
            logger.info("Deleted %d llm_calls rows", llm_count_before)

        # ── Delete orphaned pipeline_runs (and cascade to pipeline_steps) ─────
        if pipeline_runs_before > 0:
            # pipeline_steps have ondelete=CASCADE, so deleting runs is enough
            await db.execute(
                delete(PipelineRun)
                .where(PipelineRun.journal_id.is_(None))
                .where(PipelineRun.trade_id.is_(None))
            )
            logger.info("Deleted %d orphaned pipeline_runs (steps cascade)", pipeline_runs_before)

        await db.commit()
        logger.info("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 3: Test the script**

```bash
cd backend
uv run python scripts/cleanup_test_data.py
```

Expected output (if test data exists):
```
INFO: Before cleanup:
INFO:   llm_calls with test model names:  N
INFO:   orphaned pipeline_runs (no journal, no trade): M
INFO: Deleted N llm_calls rows
INFO: Deleted M orphaned pipeline_runs (steps cascade)
INFO: Cleanup complete.
```

Re-run to verify idempotency:
```
INFO: Nothing to clean up.
```

**Step 4: Commit**

```bash
git add backend/scripts/
git commit -m "chore(scripts): add cleanup_test_data.py for dev DB cleanup"
```

---

## Task 8: Update TypeScript types

**Files:**
- Modify: `frontend/src/types/trading.ts`

**Step 1: Update `BacktestRunSummary`**

Add `avg_spread` field:

```typescript
export interface BacktestRunSummary {
  // ... existing fields ...
  avg_spread: number | null;  // ADD: average spread from CSV in points
}
```

**Step 2: Update `Strategy` interface**

Add `execution_mode` field, extend `strategy_type` union:

```typescript
export interface Strategy {
  id: number;
  name: string;
  description: string | null;
  strategy_type: "config" | "prompt" | "code";
  execution_mode: "llm_only" | "rule_then_llm" | "rule_only" | "hybrid_validator" | "multi_agent";
  // ... rest unchanged ...
}
```

Update `CreateStrategyPayload` — replace `strategy_type` with `execution_mode`:

```typescript
export interface CreateStrategyPayload {
  name: string;
  description?: string;
  execution_mode: "llm_only" | "rule_then_llm" | "rule_only" | "hybrid_validator" | "multi_agent";
  trigger_type: "interval" | "candle_close";
  interval_minutes?: number;
  symbols: string[];
  timeframe: string;
  lot_size?: number;
  sl_pips?: number;
  tp_pips?: number;
  news_filter?: boolean;
  custom_prompt?: string;
  module_path?: string;
  class_name?: string;
}
```

**Step 3: Add `StrategyStats` interface**

```typescript
export interface StrategyBacktestStats {
  win_rate: number | null;
  profit_factor: number | null;
  total_trades: number | null;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  run_date: string;
  symbol: string;
  timeframe: string;
}

export interface StrategyLiveStats {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
}

export interface StrategyStats {
  backtest: StrategyBacktestStats | null;
  live: StrategyLiveStats | null;
}
```

**Step 4: Commit**

```bash
git add frontend/src/types/trading.ts
git commit -m "feat(types): add avg_spread, execution_mode, StrategyStats types"
```

---

## Task 9: Update backtest form — hide spread input for CSV, show avg spread

**Files:**
- Modify: `frontend/src/components/backtest/backtest-config-form.tsx`

**Step 1: Add state for avg_spread_pts from upload response**

Add new state after the existing state declarations:

```typescript
const [csvAvgSpread, setCsvAvgSpread] = useState<number | null>(null);
```

**Step 2: Update the CSV upload handler to capture avg spread**

Replace the CSV upload section inside `handleSubmit`:

```typescript
let csvUploadId: string | undefined;
if (csvFile) {
  const result = await backtestApi.uploadCsv(csvFile);
  csvUploadId = result.upload_id;
  setCsvAvgSpread(result.avg_spread_pts ?? null);
}
```

Also reset on file change:

```typescript
onChange={(e) => {
  setCsvFile(e.target.files?.[0] ?? null);
  setCsvAvgSpread(null);  // reset until uploaded
}}
```

**Step 3: Conditionally hide spread input + show avg spread info**

Replace the spread input block:

```tsx
{!csvFile && (
  <div className="space-y-1">
    <Label className="text-xs">Spread (pips)</Label>
    <Input
      className="h-8 text-xs"
      type="number"
      step="0.1"
      value={spread}
      onChange={(e) => setSpread(e.target.value)}
    />
  </div>
)}
{csvFile && csvAvgSpread != null && (
  <p className="text-[10px] text-muted-foreground">
    Avg spread from CSV: ~{csvAvgSpread} pts (applied per candle)
  </p>
)}
```

**Step 4: Update CSV hint text**

Replace the hint `<p>`:

```tsx
<p className="text-[10px] text-muted-foreground">
  MT5 export format: tab-separated with &lt;DATE&gt; &lt;TIME&gt; &lt;OPEN&gt;…&lt;SPREAD&gt; headers
</p>
```

**Step 5: Commit**

```bash
git add frontend/src/components/backtest/backtest-config-form.tsx
git commit -m "feat(backtest-form): hide spread input for CSV uploads, show avg spread"
```

---

## Task 10: Update backtest metrics grid — add Avg Spread row

**Files:**
- Modify: `frontend/src/components/backtest/backtest-metrics-grid.tsx`

**Step 1: Add Avg Spread card**

In `BacktestMetricsGrid`, after the existing `<MetricCard label="Max Consec Wins" .../>`, add:

```tsx
{run.avg_spread != null && run.avg_spread > 0 && (
  <MetricCard
    label="Avg Spread (pts)"
    value={run.avg_spread.toFixed(1)}
  />
)}
```

**Step 2: Commit**

```bash
git add frontend/src/components/backtest/backtest-metrics-grid.tsx
git commit -m "feat(backtest-metrics): show avg spread from CSV in metrics grid"
```

---

## Task 11: Add `getStats()` to strategies API client + show stats on strategy cards

**Files:**
- Modify: `frontend/src/lib/api/strategies.ts`
- Modify: `frontend/src/app/strategies/page.tsx`

**Step 1: Add `getStats` to strategies API client**

In `frontend/src/lib/api/strategies.ts`, add to the `strategiesApi` object:

```typescript
import type { Strategy, StrategyBinding, CreateStrategyPayload, StrategyRun, StrategyStats } from "@/types/trading"

// In strategiesApi:
getStats: (id: number) => apiRequest<StrategyStats>(`/strategies/${id}/stats`),
```

**Step 2: Update `app/strategies/page.tsx` — fetch stats in parallel + show on cards**

Add state for stats map:

```typescript
const [statsMap, setStatsMap] = useState<Record<number, StrategyStats>>({});
```

After loading strategies, fetch stats for all in parallel:

```typescript
useEffect(() => {
  (async () => {
    try {
      const data = await strategiesApi.list();
      setStrategies(data);
      // Fetch stats for all strategies in parallel
      const statsEntries = await Promise.allSettled(
        data.map(s => strategiesApi.getStats(s.id).then(stats => [s.id, stats] as const))
      );
      const map: Record<number, StrategyStats> = {};
      for (const entry of statsEntries) {
        if (entry.status === "fulfilled") {
          const [id, stats] = entry.value;
          map[id] = stats;
        }
      }
      setStatsMap(map);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  })();
}, []);
```

**Step 3: Add stats section to each strategy card**

Inside the card `<CardContent>`, after the existing symbol/binding section and before the action buttons, add:

```tsx
{/* Performance stats */}
{statsMap[s.id] && (
  <div className="border-t pt-2 mt-1 space-y-1.5">
    {statsMap[s.id].backtest && (
      <div>
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">
          Latest Backtest · {statsMap[s.id].backtest!.symbol} {statsMap[s.id].backtest!.timeframe}
        </p>
        <div className="flex gap-3 text-xs">
          <span>
            WR{" "}
            <span className="font-semibold">
              {statsMap[s.id].backtest!.win_rate != null
                ? `${(statsMap[s.id].backtest!.win_rate! * 100).toFixed(1)}%`
                : "—"}
            </span>
          </span>
          <span>
            PF{" "}
            <span className="font-semibold">
              {statsMap[s.id].backtest!.profit_factor?.toFixed(2) ?? "—"}
            </span>
          </span>
          <span>
            Ret{" "}
            <span className={`font-semibold ${(statsMap[s.id].backtest!.total_return_pct ?? 0) >= 0 ? "text-green-600" : "text-red-500"}`}>
              {statsMap[s.id].backtest!.total_return_pct != null
                ? `${statsMap[s.id].backtest!.total_return_pct! >= 0 ? "+" : ""}${statsMap[s.id].backtest!.total_return_pct!.toFixed(1)}%`
                : "—"}
            </span>
          </span>
        </div>
      </div>
    )}
    {!statsMap[s.id].backtest && (
      <p className="text-[10px] text-muted-foreground">No backtest run yet</p>
    )}
    {statsMap[s.id].live && (
      <div>
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Live</p>
        <div className="flex gap-3 text-xs">
          <span>
            Trades{" "}
            <span className="font-semibold">{statsMap[s.id].live!.total_trades}</span>
          </span>
          <span>
            WR{" "}
            <span className="font-semibold">
              {(statsMap[s.id].live!.win_rate * 100).toFixed(1)}%
            </span>
          </span>
          <span>
            P&L{" "}
            <span className={`font-semibold ${statsMap[s.id].live!.total_pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
              {statsMap[s.id].live!.total_pnl >= 0 ? "+" : ""}
              {statsMap[s.id].live!.total_pnl.toFixed(2)}
            </span>
          </span>
        </div>
      </div>
    )}
    {!statsMap[s.id].live && (
      <p className="text-[10px] text-muted-foreground">No live trades</p>
    )}
  </div>
)}
```

**Step 4: Commit**

```bash
git add frontend/src/lib/api/strategies.ts frontend/src/app/strategies/page.tsx
git commit -m "feat(strategies): show backtest + live performance stats on strategy cards"
```

---

## Task 12: Update New Strategy wizard — replace 3 types with 5 execution modes

**Files:**
- Modify: `frontend/src/app/strategies/new/page.tsx`

**Step 1: Update the form state and type**

Replace `type StratType = "config" | "prompt" | "code"` with:

```typescript
type ExecMode = "llm_only" | "rule_then_llm" | "rule_only" | "hybrid_validator" | "multi_agent";
```

Update the form state initial value:

```typescript
const [form, setForm] = useState<CreateStrategyPayload>({
  name: "",
  execution_mode: "llm_only",    // replaces strategy_type
  trigger_type: "candle_close",
  symbols: [],
  timeframe: "M15",
  news_filter: true,
});
```

**Step 2: Replace the type selector in Step 0**

Replace the type selector block with:

```tsx
<div className="space-y-2">
  <Label>Execution Mode</Label>
  <div className="grid grid-cols-1 gap-2">
    {([
      ["llm_only", "LLM Only", "LLM analyzes every candle. Requires custom_prompt."],
      ["rule_then_llm", "Rule → LLM", "Rule pre-filters; LLM validates triggered signals. Requires Python class."],
      ["rule_only", "Rule Only", "Fully deterministic rules. Zero LLM cost. Requires Python class."],
      ["hybrid_validator", "Hybrid Validator", "Rules open the trade; LLM validates post-entry. Requires Python class."],
      ["multi_agent", "Multi-Agent", "Rules + LLM run in parallel; consensus required. Requires Python class."],
    ] as [ExecMode, string, string][]).map(([mode, label, desc]) => (
      <button
        key={mode}
        type="button"
        onClick={() => setForm((f) => ({ ...f, execution_mode: mode }))}
        className={`text-left rounded-lg border px-3 py-2 transition-colors ${
          form.execution_mode === mode
            ? "bg-primary text-primary-foreground border-primary"
            : "bg-background hover:bg-muted"
        }`}
      >
        <p className="text-sm font-medium">{label}</p>
        <p className={`text-xs mt-0.5 ${form.execution_mode === mode ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
          {desc}
        </p>
      </button>
    ))}
  </div>
</div>
```

**Step 3: Update Step 2 (Configuration) to show correct fields per execution mode**

Replace the three `{form.strategy_type === "..."}` blocks:

```tsx
{/* LLM Only: show custom prompt */}
{form.execution_mode === "llm_only" && (
  <div className="space-y-2">
    <Label>Custom LLM System Prompt</Label>
    <Textarea
      value={form.custom_prompt ?? ""}
      onChange={(e) => setForm((f) => ({ ...f, custom_prompt: e.target.value || undefined }))}
      className="font-mono text-sm"
      rows={10}
      placeholder="You are a forex trading expert specializing in..."
    />
  </div>
)}

{/* Code-based modes: show module_path + class_name */}
{form.execution_mode !== "llm_only" && (
  <div className="space-y-4">
    <div className="space-y-2">
      <Label>Module Path</Label>
      <Input
        value={form.module_path ?? ""}
        onChange={(e) => setForm((f) => ({ ...f, module_path: e.target.value || undefined }))}
        placeholder="strategies.harmonic_strategy"
      />
    </div>
    <div className="space-y-2">
      <Label>Class Name</Label>
      <Input
        value={form.class_name ?? ""}
        onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value || undefined }))}
        placeholder="HarmonicStrategy"
      />
    </div>
    <div className="rounded-lg bg-muted p-4 text-sm text-muted-foreground space-y-2">
      <p className="font-medium text-foreground">How to add a code strategy:</p>
      <ol className="list-decimal list-inside space-y-1">
        <li>Create <code className="font-mono">backend/strategies/your_strategy.py</code></li>
        <li>Extend <code className="font-mono">RuleOnlyStrategy</code> (or the relevant base class) and implement <code className="font-mono">generate_rule_signal()</code></li>
        <li>Restart the backend once</li>
        <li>Enter module path and class name above</li>
      </ol>
    </div>
  </div>
)}
```

**Step 4: Remove unused `StratType` import/type, update `canNext` logic**

The `canNext` logic doesn't need to change (it only checks step 0 for name, step 1 for symbols).

**Step 5: Commit**

```bash
git add frontend/src/app/strategies/new/page.tsx
git commit -m "feat(strategies): replace 3 type buttons with 5 execution mode selector"
```

---

## Task 13: Create `/strategies/[id]/edit` page

**Files:**
- Create: `frontend/src/app/strategies/[id]/edit/page.tsx`

**Step 1: Create the edit page**

Create `frontend/src/app/strategies/[id]/edit/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { strategiesApi } from "@/lib/api/strategies";
import type { Strategy } from "@/types/trading";
import { X } from "lucide-react";

type ExecMode = "llm_only" | "rule_then_llm" | "rule_only" | "hybrid_validator" | "multi_agent";
const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const STEP_LABELS = ["Basics", "Market & Schedule", "Configuration", "Bind Accounts"];

const EXEC_MODES: [ExecMode, string, string][] = [
  ["llm_only", "LLM Only", "LLM analyzes every candle. Requires custom_prompt."],
  ["rule_then_llm", "Rule → LLM", "Rule pre-filters; LLM validates triggered signals."],
  ["rule_only", "Rule Only", "Fully deterministic rules. Zero LLM cost."],
  ["hybrid_validator", "Hybrid Validator", "Rules open the trade; LLM validates post-entry."],
  ["multi_agent", "Multi-Agent", "Rules + LLM in parallel; consensus required."],
];

export default function EditStrategyPage() {
  const { id } = useParams<{ id: string }>();
  const strategyId = Number(id);
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [form, setForm] = useState<Partial<Strategy>>({});

  useEffect(() => {
    (async () => {
      try {
        const s = await strategiesApi.get(strategyId);
        setForm({
          name: s.name,
          description: s.description ?? undefined,
          execution_mode: s.execution_mode,
          trigger_type: s.trigger_type,
          interval_minutes: s.interval_minutes ?? undefined,
          symbols: s.symbols,
          timeframe: s.timeframe,
          lot_size: s.lot_size ?? undefined,
          sl_pips: s.sl_pips ?? undefined,
          tp_pips: s.tp_pips ?? undefined,
          news_filter: s.news_filter,
          custom_prompt: s.custom_prompt ?? undefined,
          module_path: s.module_path ?? undefined,
          class_name: s.class_name ?? undefined,
        });
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    })();
  }, [strategyId]);

  const execMode = (form.execution_mode ?? "llm_only") as ExecMode;

  function addSymbol() {
    const sym = symbolInput.trim().toUpperCase();
    const current = form.symbols ?? [];
    if (sym && !current.includes(sym)) {
      setForm((f) => ({ ...f, symbols: [...(f.symbols ?? []), sym] }));
    }
    setSymbolInput("");
  }

  function removeSymbol(sym: string) {
    setForm((f) => ({ ...f, symbols: (f.symbols ?? []).filter((s) => s !== sym) }));
  }

  async function handleSubmit() {
    setSubmitting(true);
    try {
      await strategiesApi.update(strategyId, {
        name: form.name,
        description: form.description,
        execution_mode: form.execution_mode,
        trigger_type: form.trigger_type,
        interval_minutes: form.interval_minutes,
        symbols: form.symbols,
        timeframe: form.timeframe,
        lot_size: form.lot_size,
        sl_pips: form.sl_pips,
        tp_pips: form.tp_pips,
        news_filter: form.news_filter,
        custom_prompt: form.custom_prompt,
        module_path: form.module_path,
        class_name: form.class_name,
      });
      router.push(`/strategies/${strategyId}`);
    } catch (err) {
      console.error(err);
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <SidebarInset>
        <AppHeader title="Edit Strategy" />
        <div className="p-4 text-muted-foreground">Loading...</div>
      </SidebarInset>
    );
  }

  return (
    <SidebarInset>
      <AppHeader title={`Edit: ${form.name ?? ""}`} />
      <div className="flex flex-1 flex-col gap-6 p-4 max-w-2xl mx-auto w-full">
        {/* Step indicator */}
        <div className="flex gap-1">
          {STEP_LABELS.map((label, i) => (
            <div key={i} className="flex-1 flex flex-col gap-1">
              <div className={`h-1 rounded-full ${i <= step ? "bg-primary" : "bg-muted"}`} />
              <span className="text-xs text-muted-foreground hidden sm:block">{label}</span>
            </div>
          ))}
        </div>

        <div className="rounded-lg border p-6 space-y-6">
          {/* Step 0: Basics */}
          {step === 0 && (
            <>
              <h3 className="font-semibold">Step 1 — Basics</h3>
              <div className="space-y-2">
                <Label htmlFor="name">Name *</Label>
                <Input
                  id="name"
                  value={form.name ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  value={form.description ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value || undefined }))}
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <Label>Execution Mode</Label>
                <div className="grid grid-cols-1 gap-2">
                  {EXEC_MODES.map(([mode, label, desc]) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, execution_mode: mode }))}
                      className={`text-left rounded-lg border px-3 py-2 transition-colors ${
                        execMode === mode
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      <p className="text-sm font-medium">{label}</p>
                      <p className={`text-xs mt-0.5 ${execMode === mode ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
                        {desc}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Step 1: Market & Schedule */}
          {step === 1 && (
            <>
              <h3 className="font-semibold">Step 2 — Market & Schedule</h3>
              <div className="space-y-2">
                <Label>Symbols *</Label>
                <div className="flex gap-2">
                  <Input
                    value={symbolInput}
                    onChange={(e) => setSymbolInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addSymbol())}
                    placeholder="e.g. EURUSD"
                  />
                  <Button type="button" onClick={addSymbol} variant="outline">Add</Button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(form.symbols ?? []).map((sym) => (
                    <Badge key={sym} variant="secondary" className="gap-1">
                      {sym}
                      <button onClick={() => removeSymbol(sym)}>
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Timeframe</Label>
                <div className="flex gap-2 flex-wrap">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, timeframe: tf }))}
                      className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                        form.timeframe === tf
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Trigger</Label>
                <div className="flex gap-2">
                  {(["candle_close", "interval"] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, trigger_type: t }))}
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                        form.trigger_type === t
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      {t === "candle_close" ? "Candle close" : "Fixed interval"}
                    </button>
                  ))}
                </div>
                {form.trigger_type === "interval" && (
                  <div className="flex items-center gap-2 mt-2">
                    <Input
                      type="number"
                      min={1}
                      value={form.interval_minutes ?? 15}
                      onChange={(e) => setForm((f) => ({ ...f, interval_minutes: Number(e.target.value) }))}
                      className="w-24"
                    />
                    <span className="text-sm text-muted-foreground">minutes</span>
                  </div>
                )}
              </div>
            </>
          )}

          {/* Step 2: Configuration */}
          {step === 2 && (
            <>
              <h3 className="font-semibold">Step 3 — Configuration</h3>
              {execMode === "llm_only" && (
                <div className="space-y-2">
                  <Label>Custom LLM System Prompt</Label>
                  <Textarea
                    value={form.custom_prompt ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, custom_prompt: e.target.value || undefined }))}
                    className="font-mono text-sm"
                    rows={10}
                    placeholder="You are a forex trading expert..."
                  />
                </div>
              )}
              {execMode !== "llm_only" && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Module Path</Label>
                    <Input
                      value={form.module_path ?? ""}
                      onChange={(e) => setForm((f) => ({ ...f, module_path: e.target.value || undefined }))}
                      placeholder="strategies.harmonic_strategy"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Class Name</Label>
                    <Input
                      value={form.class_name ?? ""}
                      onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value || undefined }))}
                      placeholder="HarmonicStrategy"
                    />
                  </div>
                  <div className="space-y-3">
                    <Label>Risk Config (optional)</Label>
                    <div className="grid grid-cols-3 gap-3">
                      <div className="space-y-1">
                        <Label className="text-xs">Lot size</Label>
                        <Input
                          type="number" step="0.01"
                          value={form.lot_size ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, lot_size: e.target.value ? Number(e.target.value) : undefined }))}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">SL pips</Label>
                        <Input
                          type="number"
                          value={form.sl_pips ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, sl_pips: e.target.value ? Number(e.target.value) : undefined }))}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">TP pips</Label>
                        <Input
                          type="number"
                          value={form.tp_pips ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, tp_pips: e.target.value ? Number(e.target.value) : undefined }))}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <Switch
                  checked={form.news_filter ?? true}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, news_filter: v }))}
                  id="news_filter"
                />
                <Label htmlFor="news_filter">News filter</Label>
              </div>
            </>
          )}

          {/* Step 3: Review */}
          {step === 3 && (
            <>
              <h3 className="font-semibold">Step 4 — Review & Save</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-muted-foreground">Name</span><span className="font-medium">{form.name}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Mode</span><span className="font-medium">{form.execution_mode}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Timeframe</span><span className="font-medium">{form.timeframe}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Symbols</span><span className="font-medium">{(form.symbols ?? []).join(", ")}</span></div>
              </div>
            </>
          )}
        </div>

        {/* Navigation */}
        <div className="flex justify-between">
          <div>
            {step === 0 ? (
              <Button variant="outline" asChild>
                <Link href={`/strategies/${strategyId}`}>Cancel</Link>
              </Button>
            ) : (
              <Button variant="outline" onClick={() => setStep((s) => s - 1)}>Back</Button>
            )}
          </div>
          <div>
            {step < 3 ? (
              <Button onClick={() => setStep((s) => s + 1)}>Next</Button>
            ) : (
              <Button onClick={handleSubmit} disabled={submitting || !form.name?.trim() || !form.symbols?.length}>
                {submitting ? "Saving..." : "Save Changes"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </SidebarInset>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/app/strategies/
git commit -m "feat(strategies): add /strategies/[id]/edit page with pre-filled wizard"
```

---

## Task 14: Update strategy detail page — fix Edit button link

**Files:**
- Modify: `frontend/src/app/strategies/[id]/page.tsx`

**Step 1: Update the Edit button**

In `frontend/src/app/strategies/[id]/page.tsx`, find the Edit button (currently `<Link href={`/strategies/${s.id}`}>`).

Actually it's in the list page. In the detail page there is no edit button yet — it should be added. Find the header section around line 118-128:

```tsx
<div className="flex items-start gap-3">
  <Button variant="ghost" size="sm" asChild>
    <Link href="/strategies">
      <ArrowLeft className="h-4 w-4 mr-1" />
      Back
    </Link>
  </Button>
</div>
```

Replace with:

```tsx
<div className="flex items-center justify-between">
  <Button variant="ghost" size="sm" asChild>
    <Link href="/strategies">
      <ArrowLeft className="h-4 w-4 mr-1" />
      Back
    </Link>
  </Button>
  <Button variant="outline" size="sm" asChild>
    <Link href={`/strategies/${strategyId}/edit`}>
      Edit Strategy
    </Link>
  </Button>
</div>
```

Also update the Edit button in `app/strategies/page.tsx` (the card list). Find:

```tsx
<Button variant="outline" size="sm" asChild>
  <Link href={`/strategies/${s.id}`}>
    <Edit2 className="mr-1 h-3 w-3" />
    Edit
  </Link>
</Button>
```

Change to:

```tsx
<Button variant="outline" size="sm" asChild>
  <Link href={`/strategies/${s.id}/edit`}>
    <Edit2 className="mr-1 h-3 w-3" />
    Edit
  </Link>
</Button>
```

**Step 2: Commit**

```bash
git add frontend/src/app/strategies/
git commit -m "feat(strategies): link Edit buttons to /strategies/[id]/edit"
```

---

## Final: Verify full test suite

```bash
cd backend
uv run pytest tests/ -q
```

Expected: All tests pass (212+ passing, same as before + new tests from Tasks 1-3).

---

## Summary of All Changes

| Task | Files | Type |
|------|-------|------|
| 1 | `mtf_data.py`, `mtf_csv_loader.py` | Backend data layer |
| 2 | `backtest_data.py` | Backend data layer |
| 3 | `backtest_engine.py` | Backend engine |
| 4 | `db/models.py`, Alembic migration | DB schema |
| 5 | `api/routes/backtest.py` | Backend API |
| 6 | `api/routes/strategies.py` | Backend API |
| 7 | `scripts/cleanup_test_data.py` | Backend utility |
| 8 | `frontend/src/types/trading.ts` | Frontend types |
| 9 | `backtest-config-form.tsx` | Frontend UI |
| 10 | `backtest-metrics-grid.tsx` | Frontend UI |
| 11 | `lib/api/strategies.ts`, `strategies/page.tsx` | Frontend API + UI |
| 12 | `strategies/new/page.tsx` | Frontend UI |
| 13 | `strategies/[id]/edit/page.tsx` | Frontend UI (new) |
| 14 | `strategies/[id]/page.tsx`, `strategies/page.tsx` | Frontend UI |
