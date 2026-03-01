# Backtest System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full strategy backtesting system: backend async engine that replays OHLCV history through existing strategies, computes institutional-grade metrics, and a Next.js dashboard page with equity curve, monthly heatmap, trade list, and distribution chart.

**Architecture:** Custom Python event-loop engine in `backend/services/backtest_engine.py` iterates historical candles, calls the existing `strategy.generate_signal()` interface unchanged, simulates order fills (close-price or intra-candle mode), records results to two new DB tables (`backtest_runs`, `backtest_trades`), and broadcasts progress over WebSocket. Data sourced from MT5 `copy_rates_range` (new bridge method) or CSV upload.

**Tech Stack:** Python 3.12, FastAPI BackgroundTasks, SQLAlchemy 2 (async), pandas (OHLCV), Next.js 16, Recharts (equity curve, histogram), TypeScript.

---

## Task 1: DB Models — BacktestRun + BacktestTrade

**Files:**

- Modify: `backend/db/models.py`

**Step 1: Add models at the bottom of models.py**

Add after `TaskLLMAssignment`:

```python
class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_balance: Mapped[float] = mapped_column(Float, default=10000.0)
    spread_pips: Mapped[float] = mapped_column(Float, default=1.5)
    execution_mode: Mapped[str] = mapped_column(String(20), default="close_price")
    # "close_price" | "intra_candle"
    max_llm_calls: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | running | completed | failed
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Metrics — filled on completion
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_win: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_consec_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_consec_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    trades: Mapped[list["BacktestTrade"]] = relationship(
        "BacktestTrade", back_populates="run", cascade="all, delete-orphan"
    )
    strategy: Mapped["Strategy"] = relationship("Strategy")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "sl" | "tp" | "signal_reverse" | "end_of_data"
    equity_after: Mapped[float | None] = mapped_column(Float, nullable=True)

    run: Mapped["BacktestRun"] = relationship("BacktestRun", back_populates="trades")
```

**Step 2: Create Alembic migration**

```bash
cd backend
uv run alembic revision --autogenerate -m "add_backtest_tables"
uv run alembic upgrade head
```

Verify: `uv run alembic current` should show the new head revision.

---

## Task 2: BacktestMetrics Service (pure Python, fully testable)

**Files:**

- Create: `backend/services/backtest_metrics.py`
- Create: `backend/tests/test_backtest_metrics.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_backtest_metrics.py
import pytest
from services.backtest_metrics import compute_metrics


def _make_trades(profits: list[float]) -> list[dict]:
    return [{"profit": p, "equity_after": 0.0} for p in profits]


def test_empty_returns_zeros():
    m = compute_metrics([], initial_balance=10_000.0)
    assert m["total_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0


def test_all_wins():
    trades = _make_trades([100.0, 200.0, 50.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    assert m["total_trades"] == 3
    assert m["win_rate"] == 1.0
    assert m["profit_factor"] == float("inf")
    assert m["total_return_pct"] == pytest.approx(3.5, rel=1e-3)  # 350/10000


def test_profit_factor():
    trades = _make_trades([100.0, -50.0, 200.0, -100.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    # gross_profit=300, gross_loss=150 → 2.0
    assert m["profit_factor"] == pytest.approx(2.0, rel=1e-3)


def test_max_drawdown():
    # equity goes 0 → 100 → 200 → 50 → 150; peak=200 trough=50 → dd=150
    trades = _make_trades([100.0, 100.0, -150.0, 100.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    # max_drawdown_pct = 150 / 10000 = 1.5%
    assert m["max_drawdown_pct"] == pytest.approx(1.5, rel=1e-2)


def test_expectancy():
    # 2 wins avg 100, 1 loss avg -50 → (0.667*100) - (0.333*50) = 66.7 - 16.7 = 50
    trades = _make_trades([100.0, 100.0, -50.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    assert m["expectancy"] == pytest.approx(50.0, rel=1e-2)


def test_max_consecutive():
    trades = _make_trades([10, 10, -5, 10, 10, 10, -5, -5])
    m = compute_metrics(trades, initial_balance=10_000.0)
    assert m["max_consec_wins"] == 3
    assert m["max_consec_losses"] == 2
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_backtest_metrics.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.backtest_metrics'`

**Step 3: Implement `backend/services/backtest_metrics.py`**

```python
"""BacktestMetrics — compute performance statistics from a list of backtest trades.

All functions are pure Python with no I/O — easy to unit-test.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date


def compute_metrics(trades: list[dict], initial_balance: float) -> dict:
    """Compute all performance metrics from completed backtest trades.

    Args:
        trades: list of dicts with keys: profit (float), equity_after (float).
                Must be in chronological order.
        initial_balance: starting portfolio value.

    Returns:
        dict with all metric keys (see BacktestRun model).
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_drawdown_pct": 0.0,
            "recovery_factor": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "total_return_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_consec_wins": 0,
            "max_consec_losses": 0,
        }

    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total_trades = len(profits)
    win_rate = len(wins) / total_trades
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0  # negative value
    loss_rate = len(losses) / total_trades
    expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)  # avg_loss is negative

    # Equity curve from equity_after snapshots
    equity_curve = [t["equity_after"] for t in trades]

    # Max drawdown %
    peak = initial_balance
    max_dd_abs = 0.0
    running = initial_balance
    for p in profits:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd_abs:
            max_dd_abs = dd
    max_drawdown_pct = (max_dd_abs / initial_balance) * 100 if initial_balance > 0 else 0.0

    # Total return %
    total_return = sum(profits)
    total_return_pct = (total_return / initial_balance) * 100 if initial_balance > 0 else 0.0

    # Recovery factor
    recovery_factor = total_return / max_dd_abs if max_dd_abs > 0 else float("inf")

    # Sharpe / Sortino (annualised, assuming ~252 trading days)
    sharpe_ratio = _sharpe(profits)
    sortino_ratio = _sortino(profits)

    # Consecutive wins/losses
    max_consec_wins, max_consec_losses = _consecutive(profits)

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 9999.0,
        "expectancy": round(expectancy, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "recovery_factor": round(recovery_factor, 4) if recovery_factor != float("inf") else 9999.0,
        "sharpe_ratio": round(sharpe_ratio, 4),
        "sortino_ratio": round(sortino_ratio, 4),
        "total_return_pct": round(total_return_pct, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
    }


def compute_monthly_pnl(trades: list[dict]) -> list[dict]:
    """Return [{year, month, pnl, trade_count}] sorted chronologically.

    trades dicts must have: profit (float), exit_time (datetime).
    """
    monthly: dict[tuple[int, int], list[float]] = defaultdict(list)
    for t in trades:
        if t.get("exit_time") and t.get("profit") is not None:
            key = (t["exit_time"].year, t["exit_time"].month)
            monthly[key].append(t["profit"])
    return [
        {
            "year": y,
            "month": m,
            "pnl": round(sum(ps), 4),
            "trade_count": len(ps),
        }
        for (y, m), ps in sorted(monthly.items())
    ]


# ── Private helpers ────────────────────────────────────────────────────────────

def _sharpe(profits: list[float]) -> float:
    n = len(profits)
    if n < 2:
        return 0.0
    mean = sum(profits) / n
    variance = sum((p - mean) ** 2 for p in profits) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def _sortino(profits: list[float]) -> float:
    n = len(profits)
    if n < 2:
        return 0.0
    mean = sum(profits) / n
    downside = [p for p in profits if p < 0]
    if not downside:
        return float("inf")
    downside_var = sum(p ** 2 for p in downside) / n
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(252)


def _consecutive(profits: list[float]) -> tuple[int, int]:
    max_wins = max_losses = cur_wins = cur_losses = 0
    for p in profits:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
        elif p < 0:
            cur_losses += 1
            cur_wins = 0
        else:
            cur_wins = cur_losses = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return max_wins, max_losses
```

**Step 4: Run tests to verify they pass**

```bash
cd backend
uv run pytest tests/test_backtest_metrics.py -v
```

Expected: all 6 tests PASS.

**Step 5: Commit**

```bash
git add backend/services/backtest_metrics.py backend/tests/test_backtest_metrics.py
git commit -m "feat(backtest): add BacktestMetrics service with full unit tests"
```

---

## Task 3: MT5 Bridge Extension — get_rates_range

**Files:**

- Modify: `backend/mt5/bridge.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_bridge_rates_range.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_get_rates_range_returns_empty_when_mt5_unavailable():
    """When MT5 is not installed, get_rates_range raises RuntimeError."""
    from mt5.bridge import MT5Bridge, AccountCredentials
    creds = AccountCredentials(login=1, password="x", server="s")
    bridge = MT5Bridge(creds)
    with patch("mt5.bridge.MT5_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="MetaTrader5 package"):
            asyncio.run(bridge.get_rates_range("EURUSD", 16408, None, None))
```

**Step 2: Run test to verify it fails**

```bash
cd backend
uv run pytest tests/test_bridge_rates_range.py -v
```

Expected: `AttributeError: 'MT5Bridge' object has no attribute 'get_rates_range'`

**Step 3: Add `get_rates_range` to `MT5Bridge` in bridge.py**

Add after the existing `get_rates` method (around line 155):

```python
async def get_rates_range(
    self,
    symbol: str,
    timeframe: int,
    date_from: "datetime",
    date_to: "datetime",
) -> list[dict]:
    """Fetch OHLCV candles between two UTC datetimes.

    Uses copy_rates_range — designed for large historical datasets.
    Returns list of dicts with keys: time, open, high, low, close, tick_volume.
    """
    self._require_mt5()
    selected = await self._run(mt5.symbol_select, symbol, True)
    if not selected:
        err = await self.get_last_error()
        logger.warning("symbol_select(%s) failed | error=%s", symbol, err)
    rates = await self._run(mt5.copy_rates_range, symbol, timeframe, date_from, date_to)
    logger.debug(
        "copy_rates_range(%s, tf=%s, %s → %s) -> %s rows",
        symbol,
        timeframe,
        date_from,
        date_to,
        len(rates) if rates is not None else "None",
    )
    if rates is None:
        return []
    import pandas as pd  # lazy import

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.to_dict("records")
```

**Step 4: Run test to verify it passes**

```bash
cd backend
uv run pytest tests/test_bridge_rates_range.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/mt5/bridge.py backend/tests/test_bridge_rates_range.py
git commit -m "feat(backtest): add get_rates_range to MT5Bridge for historical OHLCV fetch"
```

---

## Task 4: BacktestDataService — MT5 + CSV data loading

**Files:**

- Create: `backend/services/backtest_data.py`
- Create: `backend/tests/test_backtest_data.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_backtest_data.py
import io
import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_load_from_csv_basic():
    """CSV with correct headers parses to candle dicts."""
    from services.backtest_data import BacktestDataService

    csv_content = (
        "time,open,high,low,close,tick_volume\n"
        "2020-01-02 00:00:00,1.12345,1.12400,1.12300,1.12380,100\n"
        "2020-01-02 00:15:00,1.12380,1.12450,1.12350,1.12420,120\n"
    )
    svc = BacktestDataService()
    candles = await svc.load_from_csv(io.StringIO(csv_content))
    assert len(candles) == 2
    assert candles[0]["open"] == pytest.approx(1.12345)
    assert candles[1]["close"] == pytest.approx(1.12420)


@pytest.mark.asyncio
async def test_load_from_csv_missing_column_raises():
    from services.backtest_data import BacktestDataService, BacktestDataError

    csv_content = "time,open,high,low\n2020-01-02,1.1,1.2,1.0\n"
    svc = BacktestDataService()
    with pytest.raises(BacktestDataError, match="Missing columns"):
        await svc.load_from_csv(io.StringIO(csv_content))
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_backtest_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.backtest_data'`

**Step 3: Implement `backend/services/backtest_data.py`**

```python
"""BacktestDataService — load historical OHLCV from MT5 or CSV.

MT5 path: requires a connected MT5Bridge (caller provides it).
CSV path: accepts a file-like object (StringIO or UploadFile.file).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_CSV_COLUMNS = {"time", "open", "high", "low", "close", "tick_volume"}


class BacktestDataError(ValueError):
    """Raised when OHLCV data cannot be loaded or is invalid."""


class BacktestDataService:
    async def load_from_mt5(
        self,
        bridge,  # MT5Bridge instance (already connected)
        symbol: str,
        timeframe: int,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict]:
        """Fetch OHLCV candles from MT5 for the given date range.

        Returns list of dicts: time (datetime, UTC-aware), open, high, low,
        close, tick_volume.  Raises BacktestDataError on failure.
        """
        try:
            candles = await bridge.get_rates_range(symbol, timeframe, date_from, date_to)
        except Exception as exc:
            raise BacktestDataError(f"MT5 fetch failed: {exc}") from exc

        if not candles:
            raise BacktestDataError(
                f"No data returned for {symbol} {date_from.date()} → {date_to.date()}. "
                "Check that the symbol is available in Market Watch and MT5 has history downloaded."
            )
        logger.info("Loaded %d candles from MT5 | %s %s→%s", len(candles), symbol, date_from.date(), date_to.date())
        return candles

    async def load_from_csv(self, file: io.StringIO | io.BytesIO) -> list[dict]:
        """Parse a CSV file into a list of OHLCV candle dicts.

        Expected CSV columns: time, open, high, low, close, tick_volume.
        'time' must be parseable by pandas (e.g. '2020-01-02 00:00:00').
        """
        try:
            df = pd.read_csv(file)
        except Exception as exc:
            raise BacktestDataError(f"Failed to parse CSV: {exc}") from exc

        df.columns = [c.strip().lower() for c in df.columns]
        missing = REQUIRED_CSV_COLUMNS - set(df.columns)
        if missing:
            raise BacktestDataError(f"Missing columns in CSV: {sorted(missing)}")

        try:
            df["time"] = pd.to_datetime(df["time"], utc=True)
        except Exception as exc:
            raise BacktestDataError(f"Cannot parse 'time' column: {exc}") from exc

        df = df.sort_values("time").reset_index(drop=True)
        logger.info("Loaded %d candles from CSV", len(df))
        return df[["time", "open", "high", "low", "close", "tick_volume"]].to_dict("records")
```

**Step 4: Run tests to verify they pass**

```bash
cd backend
uv run pytest tests/test_backtest_data.py -v
```

Expected: 2 tests PASS.

**Step 5: Commit**

```bash
git add backend/services/backtest_data.py backend/tests/test_backtest_data.py
git commit -m "feat(backtest): add BacktestDataService with MT5 + CSV loading"
```

---

## Task 5: BacktestEngine — core event loop

**Files:**

- Create: `backend/services/backtest_engine.py`
- Create: `backend/tests/test_backtest_engine.py`

**Step 1: Write the failing tests**

```python
# backend/tests/test_backtest_engine.py
"""Test the backtest event loop with a synthetic strategy and OHLCV data."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


def _make_candles(n: int, base_price: float = 1.10000) -> list[dict]:
    """Generate n synthetic M15 candles moving up by 1 pip per bar."""
    candles = []
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    price = base_price
    for i in range(n):
        candles.append({
            "time": t,
            "open": price,
            "high": price + 0.00050,
            "low": price - 0.00030,
            "close": price + 0.00010,
            "tick_volume": 100,
        })
        price += 0.00001
        t += timedelta(minutes=15)
    return candles


def _always_buy_strategy():
    """Strategy that always returns BUY with 20-pip SL and 40-pip TP."""
    m = MagicMock()
    def signal(market_data):
        price = market_data["current_price"]
        return {
            "action": "BUY",
            "entry": price,
            "stop_loss": round(price - 0.0020, 5),
            "take_profit": round(price + 0.0040, 5),
            "confidence": 0.9,
            "rationale": "always buy",
            "timeframe": "M15",
        }
    m.generate_signal.side_effect = signal
    m.strategy_type = "code"
    return m


@pytest.mark.asyncio
async def test_engine_returns_trades_list():
    from services.backtest_engine import BacktestEngine
    candles = _make_candles(60)  # 60 candles, ~15 hours
    strategy = _always_buy_strategy()
    config = {
        "symbol": "EURUSD",
        "timeframe": "M15",
        "initial_balance": 10_000.0,
        "spread_pips": 1.0,
        "execution_mode": "close_price",
        "volume": 0.1,
        "max_llm_calls": 0,
    }
    engine = BacktestEngine()
    result = await engine.run(candles, strategy, config, progress_cb=None)
    assert "trades" in result
    assert "equity_curve" in result
    assert isinstance(result["trades"], list)


@pytest.mark.asyncio
async def test_engine_sl_closes_position():
    """When price drops to SL, position should be closed with SL exit reason."""
    from services.backtest_engine import BacktestEngine

    # Candle 0: BUY signal at 1.10000, SL=1.09800, TP=1.10400
    # Candle 1: low goes below SL → should be closed
    candles = [
        {"time": datetime(2020, 1, 2, tzinfo=timezone.utc),
         "open": 1.10000, "high": 1.10050, "low": 1.09990, "close": 1.10010, "tick_volume": 100},
        {"time": datetime(2020, 1, 2, 0, 15, tzinfo=timezone.utc),
         "open": 1.10010, "high": 1.10020, "low": 1.09700, "close": 1.09750, "tick_volume": 100},
        {"time": datetime(2020, 1, 2, 0, 30, tzinfo=timezone.utc),
         "open": 1.09750, "high": 1.09800, "low": 1.09700, "close": 1.09720, "tick_volume": 100},
    ]
    strategy = _always_buy_strategy()
    config = {
        "symbol": "EURUSD",
        "timeframe": "M15",
        "initial_balance": 10_000.0,
        "spread_pips": 0.0,
        "execution_mode": "intra_candle",
        "volume": 0.1,
        "max_llm_calls": 0,
    }
    engine = BacktestEngine()
    result = await engine.run(candles, strategy, config, progress_cb=None)
    closed = [t for t in result["trades"] if t["exit_reason"] is not None]
    assert len(closed) >= 1
    sl_closed = [t for t in closed if t["exit_reason"] == "sl"]
    assert len(sl_closed) >= 1
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_backtest_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.backtest_engine'`

**Step 3: Implement `backend/services/backtest_engine.py`**

```python
"""BacktestEngine — event-driven simulation of a trading strategy on OHLCV history.

Design:
  - Iterates candles chronologically, one at a time (event-driven, not vectorised).
  - Calls strategy.generate_signal(market_data) at each candle, using the same
    interface as live trading (no strategy code changes required).
  - Two fill modes:
      close_price:  entry and SL/TP checks at candle close
      intra_candle: entry at next open + spread; SL/TP checked during candle H/L
  - LLM strategies are sampled: LLM called every N-th candle (budget = max_llm_calls).
  - One open position per symbol at a time (matching live behaviour).
  - progress_cb(pct: int) is called every 1,000 candles if provided.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Number of candles in the rolling window passed to strategy.generate_signal()
_WINDOW = 50


class BacktestEngine:

    async def run(
        self,
        candles: list[dict],
        strategy,
        config: dict,
        progress_cb: Callable[[int], Awaitable[None]] | None,
    ) -> dict:
        """Run the backtest simulation.

        Args:
            candles:     Chronological list of OHLCV candle dicts.
            strategy:    Any object with .generate_signal(market_data) -> dict | None
                         and .strategy_type (str: "code" | "config" | "prompt").
            config:      {symbol, timeframe, initial_balance, spread_pips,
                         execution_mode, volume, max_llm_calls}
            progress_cb: Optional async callback(pct: int) called every 1_000 candles.

        Returns:
            {trades: list[dict], equity_curve: list[dict]}
        """
        symbol = config["symbol"]
        timeframe = config["timeframe"]
        balance = config["initial_balance"]
        spread = config.get("spread_pips", 1.5) * _pip_value(symbol)
        mode = config.get("execution_mode", "close_price")
        volume = config.get("volume", 0.1)
        max_llm = config.get("max_llm_calls", 100)
        total = len(candles)

        # LLM sampling step: call LLM every K-th candle
        is_llm_strategy = getattr(strategy, "strategy_type", "code") in ("config", "prompt")
        llm_step = max(1, total // max_llm) if is_llm_strategy and max_llm > 0 else None

        open_position: dict | None = None  # one position at a time
        trades: list[dict] = []
        equity_curve: list[dict] = []
        last_signal: dict | None = None

        for i, candle in enumerate(candles):
            # ── 1. Check open position SL/TP ──────────────────────────────────
            if open_position is not None:
                closed = _check_exit(open_position, candle, mode)
                if closed:
                    profit = _calc_profit(open_position, closed["exit_price"], volume, symbol)
                    balance += profit
                    trade = {**open_position, **closed, "profit": round(profit, 4),
                             "equity_after": round(balance, 4)}
                    trades.append(trade)
                    equity_curve.append({"time": closed["exit_time"], "equity": round(balance, 4)})
                    open_position = None

            # ── 2. Generate signal ─────────────────────────────────────────────
            if open_position is None and i >= _WINDOW - 1:
                window = candles[max(0, i - _WINDOW + 1): i + 1]
                market_data = _build_market_data(symbol, timeframe, candle, window)

                # For LLM strategies, only call on sampled candles; hold last signal between
                if is_llm_strategy and llm_step and (i % llm_step != 0):
                    signal = last_signal
                else:
                    try:
                        signal = strategy.generate_signal(market_data)
                    except Exception as exc:
                        logger.warning("generate_signal error at candle %d: %s", i, exc)
                        signal = None
                    last_signal = signal

                # ── 3. Open new position ───────────────────────────────────────
                if signal and signal.get("action") in ("BUY", "SELL"):
                    fill_price = _fill_price(signal, candle, candles, i, mode, spread)
                    if fill_price is not None:
                        open_position = {
                            "symbol": symbol,
                            "direction": signal["action"],
                            "entry_time": candle["time"],
                            "entry_price": round(fill_price, 5),
                            "stop_loss": round(signal["stop_loss"], 5),
                            "take_profit": round(signal["take_profit"], 5),
                            "volume": volume,
                            "exit_time": None,
                            "exit_price": None,
                            "exit_reason": None,
                            "profit": None,
                            "equity_after": None,
                        }

            # ── 4. Progress callback ───────────────────────────────────────────
            if progress_cb and i % 1000 == 0:
                pct = int(i / total * 100)
                await progress_cb(pct)

        # ── Close any open position at end of data ─────────────────────────────
        if open_position is not None:
            last_candle = candles[-1]
            profit = _calc_profit(open_position, last_candle["close"], volume, symbol)
            balance += profit
            trade = {
                **open_position,
                "exit_time": last_candle["time"],
                "exit_price": round(last_candle["close"], 5),
                "exit_reason": "end_of_data",
                "profit": round(profit, 4),
                "equity_after": round(balance, 4),
            }
            trades.append(trade)
            equity_curve.append({"time": last_candle["time"], "equity": round(balance, 4)})

        logger.info("Backtest complete | %d candles | %d trades | final_equity=%.2f",
                    total, len(trades), balance)
        return {"trades": trades, "equity_curve": equity_curve}


# ── Private helpers ────────────────────────────────────────────────────────────

def _pip_value(symbol: str) -> float:
    """Convert 1 pip to price units. JPY pairs use 0.01, others 0.0001."""
    return 0.01 if "JPY" in symbol else 0.0001


def _check_exit(pos: dict, candle: dict, mode: str) -> dict | None:
    """Return exit info dict or None if position stays open."""
    direction = pos["direction"]
    sl = pos["stop_loss"]
    tp = pos["take_profit"]
    t = candle["time"]

    if mode == "close_price":
        price = candle["close"]
        if direction == "BUY":
            if price <= sl:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if price >= tp:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
        else:  # SELL
            if price >= sl:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if price <= tp:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
    else:  # intra_candle
        high, low = candle["high"], candle["low"]
        open_p = candle["open"]
        if direction == "BUY":
            sl_hit = low <= sl
            tp_hit = high >= tp
            if sl_hit and tp_hit:
                # whichever is closer to open wins
                return ({"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
                        if abs(open_p - sl) <= abs(open_p - tp)
                        else {"exit_time": t, "exit_price": tp, "exit_reason": "tp"})
            if sl_hit:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if tp_hit:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
        else:  # SELL
            sl_hit = high >= sl
            tp_hit = low <= tp
            if sl_hit and tp_hit:
                return ({"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
                        if abs(open_p - sl) <= abs(open_p - tp)
                        else {"exit_time": t, "exit_price": tp, "exit_reason": "tp"})
            if sl_hit:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if tp_hit:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
    return None


def _fill_price(signal: dict, candle: dict, candles: list, i: int, mode: str, spread: float) -> float | None:
    """Determine fill price based on execution mode."""
    if mode == "close_price":
        return candle["close"]
    # intra_candle: fill at next open + spread (for BUY) or - spread (for SELL)
    if i + 1 < len(candles):
        next_open = candles[i + 1]["open"]
        return next_open + spread if signal["action"] == "BUY" else next_open - spread
    return None  # no next candle, skip


def _calc_profit(pos: dict, exit_price: float, volume: float, symbol: str) -> float:
    """Calculate P&L in account currency (simplified: 1 lot = 100,000 units).

    For forex: profit = (exit - entry) * direction_sign * volume * contract_size
    """
    contract_size = 100_000
    pip = _pip_value(symbol)
    entry = pos["entry_price"]
    direction_sign = 1 if pos["direction"] == "BUY" else -1
    price_diff = (exit_price - entry) * direction_sign
    return price_diff * volume * contract_size


def _build_market_data(symbol: str, timeframe: str, candle: dict, window: list[dict]) -> dict:
    """Build the market_data dict expected by strategy.generate_signal()."""
    closes = [c["close"] for c in window]
    sma_20 = sum(closes[-20:]) / min(20, len(closes))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": candle["close"],
        "candles": window,
        "indicators": {
            "sma_20": round(sma_20, 5),
            "recent_high": max(c["high"] for c in window),
            "recent_low": min(c["low"] for c in window),
            "candle_count": len(window),
        },
        "open_positions": [],   # backtest: no other positions
        "recent_signals": [],   # backtest: no signal history
    }
```

**Step 4: Run tests to verify they pass**

```bash
cd backend
uv run pytest tests/test_backtest_engine.py -v
```

Expected: 2 tests PASS.

**Step 5: Commit**

```bash
git add backend/services/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): add BacktestEngine event-loop with close_price and intra_candle modes"
```

---

## Task 6: API Routes — /api/v1/backtest

**Files:**

- Create: `backend/api/routes/backtest.py`
- Modify: `backend/main.py`

**Step 1: Create `backend/api/routes/backtest.py`**

```python
"""Backtest API — submit runs, poll status, retrieve results."""
from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.ws import broadcast_all
from db.models import BacktestRun, BacktestTrade, Strategy
from db.postgres import get_db, AsyncSessionLocal
from services.backtest_data import BacktestDataService, BacktestDataError
from services.backtest_engine import BacktestEngine
from services.backtest_metrics import compute_metrics, compute_monthly_pnl

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class BacktestRunRequest(BaseModel):
    strategy_id: int
    symbol: str = Field(..., min_length=1, max_length=20)
    timeframe: str = Field(default="M15")
    start_date: datetime
    end_date: datetime
    initial_balance: float = Field(default=10_000.0, gt=0)
    spread_pips: float = Field(default=1.5, ge=0)
    execution_mode: str = Field(default="close_price")
    max_llm_calls: int = Field(default=100, ge=0)
    volume: float = Field(default=0.1, gt=0)
    csv_upload_id: str | None = None  # temp file ID from /data/upload


class BacktestRunSummary(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    spread_pips: float
    execution_mode: str
    status: str
    progress_pct: int
    error_message: str | None
    total_trades: int | None
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    max_drawdown_pct: float | None
    recovery_factor: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    total_return_pct: float | None
    avg_win: float | None
    avg_loss: float | None
    max_consec_wins: int | None
    max_consec_losses: int | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, r: BacktestRun) -> "BacktestRunSummary":
        return cls(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            timeframe=r.timeframe,
            start_date=r.start_date.isoformat(),
            end_date=r.end_date.isoformat(),
            initial_balance=r.initial_balance,
            spread_pips=r.spread_pips,
            execution_mode=r.execution_mode,
            status=r.status,
            progress_pct=r.progress_pct,
            error_message=r.error_message,
            total_trades=r.total_trades,
            win_rate=r.win_rate,
            profit_factor=r.profit_factor,
            expectancy=r.expectancy,
            max_drawdown_pct=r.max_drawdown_pct,
            recovery_factor=r.recovery_factor,
            sharpe_ratio=r.sharpe_ratio,
            sortino_ratio=r.sortino_ratio,
            total_return_pct=r.total_return_pct,
            avg_win=r.avg_win,
            avg_loss=r.avg_loss,
            max_consec_wins=r.max_consec_wins,
            max_consec_losses=r.max_consec_losses,
            created_at=r.created_at.isoformat(),
        )


class BacktestTradeOut(BaseModel):
    id: int
    run_id: int
    symbol: str
    direction: str
    entry_time: str
    exit_time: str | None
    entry_price: float
    exit_price: float | None
    stop_loss: float
    take_profit: float
    volume: float
    profit: float | None
    exit_reason: str | None
    equity_after: float | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, t: BacktestTrade) -> "BacktestTradeOut":
        return cls(
            id=t.id,
            run_id=t.run_id,
            symbol=t.symbol,
            direction=t.direction,
            entry_time=t.entry_time.isoformat(),
            exit_time=t.exit_time.isoformat() if t.exit_time else None,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            stop_loss=t.stop_loss,
            take_profit=t.take_profit,
            volume=t.volume,
            profit=t.profit,
            exit_reason=t.exit_reason,
            equity_after=t.equity_after,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/runs", response_model=BacktestRunSummary, status_code=202)
async def submit_run(
    req: BacktestRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> BacktestRunSummary:
    """Submit a new backtest job. Returns immediately with run_id; job runs in background."""
    strategy = await db.get(Strategy, req.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Validate execution_mode
    if req.execution_mode not in ("close_price", "intra_candle"):
        raise HTTPException(status_code=422, detail="execution_mode must be 'close_price' or 'intra_candle'")

    # Use strategy timeframe if not overridden
    timeframe = req.timeframe or strategy.timeframe

    run = BacktestRun(
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        timeframe=timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_balance=req.initial_balance,
        spread_pips=req.spread_pips,
        execution_mode=req.execution_mode,
        max_llm_calls=req.max_llm_calls,
        status="pending",
        progress_pct=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(
        _run_backtest_job,
        run_id=run.id,
        req=req,
        strategy_db=strategy,
        timeframe=timeframe,
    )
    logger.info("Backtest run %d submitted | strategy=%s symbol=%s", run.id, strategy.name, run.symbol)
    return BacktestRunSummary.from_orm(run)


@router.get("/runs", response_model=list[BacktestRunSummary])
async def list_runs(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestRunSummary]:
    q = select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit).offset(offset)
    runs = (await db.execute(q)).scalars().all()
    return [BacktestRunSummary.from_orm(r) for r in runs]


@router.get("/runs/{run_id}", response_model=BacktestRunSummary)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> BacktestRunSummary:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestRunSummary.from_orm(run)


@router.get("/runs/{run_id}/trades", response_model=list[BacktestTradeOut])
async def get_trades(
    run_id: int,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestTradeOut]:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade)
        .where(BacktestTrade.run_id == run_id)
        .order_by(BacktestTrade.entry_time)
        .limit(limit)
        .offset(offset)
    )
    trades = (await db.execute(q)).scalars().all()
    return [BacktestTradeOut.from_orm(t) for t in trades]


@router.get("/runs/{run_id}/equity-curve")
async def get_equity_curve(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return [{time, equity}] array for chart rendering."""
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade.exit_time, BacktestTrade.equity_after)
        .where(BacktestTrade.run_id == run_id)
        .where(BacktestTrade.exit_time.is_not(None))
        .order_by(BacktestTrade.exit_time)
    )
    rows = (await db.execute(q)).all()
    return [{"time": r.exit_time.isoformat(), "equity": r.equity_after} for r in rows]


@router.get("/runs/{run_id}/monthly-pnl")
async def get_monthly_pnl(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return [{year, month, pnl, trade_count}] for the monthly heatmap."""
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade)
        .where(BacktestTrade.run_id == run_id)
        .where(BacktestTrade.exit_time.is_not(None))
        .order_by(BacktestTrade.exit_time)
    )
    trades = (await db.execute(q)).scalars().all()
    trade_dicts = [{"profit": t.profit, "exit_time": t.exit_time} for t in trades]
    return compute_monthly_pnl(trade_dicts)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: int, db: AsyncSession = Depends(get_db)) -> None:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    await db.delete(run)
    await db.commit()


@router.post("/data/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    """Save uploaded CSV to a temp file and return an upload_id for use in run submission."""
    suffix = ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as f:
        content = await file.read()
        f.write(content)
        tmp_path = f.name
    logger.info("CSV uploaded: %s (%d bytes)", tmp_path, len(content))
    return {"upload_id": tmp_path, "size_bytes": len(content)}


# ── Background job ─────────────────────────────────────────────────────────────

async def _run_backtest_job(
    run_id: int,
    req: BacktestRunRequest,
    strategy_db,
    timeframe: str,
) -> None:
    """Background task: load data, run engine, persist results."""
    async with AsyncSessionLocal() as db:
        run = await db.get(BacktestRun, run_id)
        if not run:
            return

        run.status = "running"
        await db.commit()
        await broadcast_all("backtest_progress", {"run_id": run_id, "progress_pct": 0})

        try:
            # ── Load OHLCV data ────────────────────────────────────────────────
            data_svc = BacktestDataService()
            candles: list[dict]

            if req.csv_upload_id:
                import io
                with open(req.csv_upload_id, "r") as f:
                    candles = await data_svc.load_from_csv(io.StringIO(f.read()))
            else:
                # MT5 path — requires MT5 to be running
                from mt5.bridge import MT5Bridge, AccountCredentials, MT5_AVAILABLE
                if not MT5_AVAILABLE:
                    raise BacktestDataError(
                        "MT5 is not available. Please upload a CSV file instead."
                    )
                # Use first active account's credentials
                from db.models import Account
                from sqlalchemy import select as sa_select
                account = (await db.execute(
                    sa_select(Account).where(Account.is_active == True).limit(1)  # noqa: E712
                )).scalars().first()
                if not account:
                    raise BacktestDataError("No active MT5 account found")
                from core.security import decrypt_value
                creds = AccountCredentials(
                    login=account.login,
                    password=decrypt_value(account.password_encrypted),
                    server=account.server,
                    path=account.mt5_path or "",
                )
                # MT5 timeframe int from string
                tf_int = _timeframe_to_int(timeframe)
                async with MT5Bridge(creds) as bridge:
                    candles = await data_svc.load_from_mt5(
                        bridge, req.symbol, tf_int, req.start_date, req.end_date
                    )

            # ── Load strategy instance ─────────────────────────────────────────
            strategy_instance = _load_strategy(strategy_db)

            # ── Run engine ────────────────────────────────────────────────────
            engine = BacktestEngine()
            config = {
                "symbol": req.symbol,
                "timeframe": timeframe,
                "initial_balance": req.initial_balance,
                "spread_pips": req.spread_pips,
                "execution_mode": req.execution_mode,
                "volume": req.volume,
                "max_llm_calls": req.max_llm_calls,
            }

            async def _progress(pct: int) -> None:
                async with AsyncSessionLocal() as progress_db:
                    r = await progress_db.get(BacktestRun, run_id)
                    if r:
                        r.progress_pct = pct
                        await progress_db.commit()
                await broadcast_all("backtest_progress", {"run_id": run_id, "progress_pct": pct})

            result = await engine.run(candles, strategy_instance, config, progress_cb=_progress)

            # ── Persist trades ────────────────────────────────────────────────
            for trade_dict in result["trades"]:
                bt = BacktestTrade(
                    run_id=run_id,
                    symbol=trade_dict["symbol"],
                    direction=trade_dict["direction"],
                    entry_time=trade_dict["entry_time"],
                    exit_time=trade_dict.get("exit_time"),
                    entry_price=trade_dict["entry_price"],
                    exit_price=trade_dict.get("exit_price"),
                    stop_loss=trade_dict["stop_loss"],
                    take_profit=trade_dict["take_profit"],
                    volume=trade_dict["volume"],
                    profit=trade_dict.get("profit"),
                    exit_reason=trade_dict.get("exit_reason"),
                    equity_after=trade_dict.get("equity_after"),
                )
                db.add(bt)
            await db.flush()

            # ── Compute metrics ────────────────────────────────────────────────
            closed = [t for t in result["trades"] if t.get("profit") is not None]
            metrics = compute_metrics(closed, req.initial_balance)

            run.status = "completed"
            run.progress_pct = 100
            run.total_trades = metrics["total_trades"]
            run.win_rate = metrics["win_rate"]
            run.profit_factor = metrics["profit_factor"]
            run.expectancy = metrics["expectancy"]
            run.max_drawdown_pct = metrics["max_drawdown_pct"]
            run.recovery_factor = metrics["recovery_factor"]
            run.sharpe_ratio = metrics["sharpe_ratio"]
            run.sortino_ratio = metrics["sortino_ratio"]
            run.total_return_pct = metrics["total_return_pct"]
            run.avg_win = metrics["avg_win"]
            run.avg_loss = metrics["avg_loss"]
            run.max_consec_wins = metrics["max_consec_wins"]
            run.max_consec_losses = metrics["max_consec_losses"]
            await db.commit()

            await broadcast_all("backtest_complete", {
                "run_id": run_id,
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
            })
            logger.info("Backtest run %d completed | %d trades", run_id, metrics["total_trades"])

        except Exception as exc:
            logger.error("Backtest run %d failed: %s", run_id, exc, exc_info=True)
            run.status = "failed"
            run.error_message = str(exc)[:500]
            await db.commit()
            await broadcast_all("backtest_failed", {"run_id": run_id, "error": str(exc)[:200]})


def _load_strategy(strategy_db):
    """Load and instantiate a Strategy model into a BaseStrategy subclass instance.

    For code-type strategies: dynamically imports module_path.class_name.
    For config/prompt types: creates a minimal wrapper that returns None from
    generate_signal (triggering the LLM path during backtest).
    """
    if strategy_db.strategy_type == "code" and strategy_db.module_path and strategy_db.class_name:
        import importlib
        mod = importlib.import_module(strategy_db.module_path)
        cls = getattr(mod, strategy_db.class_name)
        instance = cls()
        instance.strategy_type = "code"
        return instance

    # Config / prompt strategy: wrap DB config in a minimal object
    class _ConfigStrategy:
        strategy_type = strategy_db.strategy_type  # "config" | "prompt"
        sl_pips_val = strategy_db.sl_pips or 20.0
        tp_pips_val = strategy_db.tp_pips or 40.0
        prompt = strategy_db.custom_prompt

        def generate_signal(self, market_data: dict) -> dict | None:
            return None  # triggers LLM path (sampled by engine)

        def system_prompt(self) -> str | None:
            return self.prompt

    return _ConfigStrategy()


def _timeframe_to_int(tf: str) -> int:
    """Convert timeframe string to MT5 TIMEFRAME constant integer."""
    mapping = {
        "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5,
        "M6": 6, "M10": 10, "M12": 12, "M15": 15, "M20": 20,
        "M30": 30, "H1": 16385, "H2": 16386, "H3": 16387,
        "H4": 16388, "H6": 16390, "H8": 16392, "H12": 16396,
        "D1": 16408, "W1": 32769, "MN1": 49153,
    }
    return mapping.get(tf.upper(), 15)
```

**Step 2: Register route in main.py**

Add these two lines to `backend/main.py`:

After the last existing import line add:

```python
from api.routes import backtest as backtest_routes
```

After the last `app.include_router(...)` line add:

```python
app.include_router(backtest_routes.router, prefix="/api/v1/backtest", tags=["backtest"])
```

**Step 3: Verify backend starts**

```bash
cd backend
uv run uvicorn main:app --reload --port 8000
```

Expected: server starts, no import errors. Check `http://localhost:8000/docs` shows `/api/v1/backtest/*` routes.

**Step 4: Commit**

```bash
git add backend/api/routes/backtest.py backend/main.py
git commit -m "feat(backtest): add /api/v1/backtest API routes with background job execution"
```

---

## Task 7: Frontend — Types + API Client

**Files:**

- Modify: `frontend/src/types/trading.ts`
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add types to `frontend/src/types/trading.ts`**

Append to the end of the file:

```typescript
// ── Backtest ──────────────────────────────────────────────────────────────────

export interface BacktestRunSummary {
  id: number;
  strategy_id: number;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_balance: number;
  spread_pips: number;
  execution_mode: string;
  status: "pending" | "running" | "completed" | "failed";
  progress_pct: number;
  error_message: string | null;
  total_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  max_drawdown_pct: number | null;
  recovery_factor: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  total_return_pct: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  max_consec_wins: number | null;
  max_consec_losses: number | null;
  created_at: string;
}

export interface BacktestTrade {
  id: number;
  run_id: number;
  symbol: string;
  direction: "BUY" | "SELL";
  entry_time: string;
  exit_time: string | null;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number;
  take_profit: number;
  volume: number;
  profit: number | null;
  exit_reason: "sl" | "tp" | "signal_reverse" | "end_of_data" | null;
  equity_after: number | null;
}

export interface BacktestEquityPoint {
  time: string;
  equity: number;
}

export interface BacktestMonthlyPnl {
  year: number;
  month: number;
  pnl: number;
  trade_count: number;
}

export interface BacktestRunRequest {
  strategy_id: number;
  symbol: string;
  timeframe?: string;
  start_date: string;
  end_date: string;
  initial_balance?: number;
  spread_pips?: number;
  execution_mode?: "close_price" | "intra_candle";
  max_llm_calls?: number;
  volume?: number;
  csv_upload_id?: string;
}
```

**Step 2: Add backtestApi to `frontend/src/lib/api.ts`**

Append to the end of the file:

```typescript
// ── Backtest ──────────────────────────────────────────────────────────────────

export const backtestApi = {
  submitRun: (req: import("@/types/trading").BacktestRunRequest) =>
    apiRequest<import("@/types/trading").BacktestRunSummary>("/backtest/runs", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  listRuns: (params?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").BacktestRunSummary[]>(
      `/backtest/runs${qs ? `?${qs}` : ""}`,
    );
  },

  getRun: (runId: number) =>
    apiRequest<import("@/types/trading").BacktestRunSummary>(
      `/backtest/runs/${runId}`,
    ),

  getTrades: (runId: number, params?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").BacktestTrade[]>(
      `/backtest/runs/${runId}/trades${qs ? `?${qs}` : ""}`,
    );
  },

  getEquityCurve: (runId: number) =>
    apiRequest<import("@/types/trading").BacktestEquityPoint[]>(
      `/backtest/runs/${runId}/equity-curve`,
    ),

  getMonthlyPnl: (runId: number) =>
    apiRequest<import("@/types/trading").BacktestMonthlyPnl[]>(
      `/backtest/runs/${runId}/monthly-pnl`,
    ),

  deleteRun: (runId: number) =>
    apiRequest<void>(`/backtest/runs/${runId}`, { method: "DELETE" }),

  uploadCsv: async (
    file: File,
  ): Promise<{ upload_id: string; size_bytes: number }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_V1}/backtest/data/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(
        (err as { detail?: string }).detail ||
          `Upload failed: ${res.statusText}`,
      );
    }
    return res.json();
  },
};
```

**Step 3: Commit**

```bash
git add frontend/src/types/trading.ts frontend/src/lib/api.ts
git commit -m "feat(backtest): add BacktestRunSummary/BacktestTrade types and backtestApi client"
```

---

## Task 8: Frontend — Backtest Components

**Files:**

- Create: `frontend/src/components/backtest/backtest-config-form.tsx`
- Create: `frontend/src/components/backtest/backtest-run-list.tsx`
- Create: `frontend/src/components/backtest/backtest-metrics-grid.tsx`
- Create: `frontend/src/components/backtest/equity-curve-chart.tsx`
- Create: `frontend/src/components/backtest/monthly-heatmap.tsx`
- Create: `frontend/src/components/backtest/backtest-trade-table.tsx`
- Create: `frontend/src/components/backtest/backtest-results.tsx`

**Step 1: Create `frontend/src/components/backtest/backtest-config-form.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { backtestApi } from "@/lib/api";
import type { BacktestRunRequest, BacktestRunSummary } from "@/types/trading";

interface Strategy {
  id: number;
  name: string;
  timeframe: string;
  strategy_type: string;
}

interface Props {
  strategies: Strategy[];
  onRunCreated: (run: BacktestRunSummary) => void;
}

const SIX_YEARS_AGO = new Date();
SIX_YEARS_AGO.setFullYear(SIX_YEARS_AGO.getFullYear() - 6);

export function BacktestConfigForm({ strategies, onRunCreated }: Props) {
  const [strategyId, setStrategyId] = useState<string>("");
  const [symbol, setSymbol] = useState("EURUSD");
  const [startDate, setStartDate] = useState(SIX_YEARS_AGO.toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [balance, setBalance] = useState("10000");
  const [spread, setSpread] = useState("1.5");
  const [mode, setMode] = useState<"close_price" | "intra_candle">("close_price");
  const [maxLlm, setMaxLlm] = useState("100");
  const [volume, setVolume] = useState("0.1");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!strategyId) { setError("Select a strategy"); return; }
    setError(null);
    setSubmitting(true);

    try {
      let csvUploadId: string | undefined;
      if (csvFile) {
        setUploading(true);
        const result = await backtestApi.uploadCsv(csvFile);
        csvUploadId = result.upload_id;
        setUploading(false);
      }

      const req: BacktestRunRequest = {
        strategy_id: Number(strategyId),
        symbol,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        initial_balance: Number(balance),
        spread_pips: Number(spread),
        execution_mode: mode,
        max_llm_calls: Number(maxLlm),
        volume: Number(volume),
        csv_upload_id: csvUploadId,
      };
      const run = await backtestApi.submitRun(req);
      onRunCreated(run);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1">
        <Label>Strategy</Label>
        <Select value={strategyId} onValueChange={setStrategyId}>
          <SelectTrigger><SelectValue placeholder="Select strategy" /></SelectTrigger>
          <SelectContent>
            {strategies.map((s) => (
              <SelectItem key={s.id} value={String(s.id)}>
                {s.name} ({s.timeframe})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label>Symbol</Label>
        <Input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label>Start Date</Label>
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>End Date</Label>
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label>Initial Balance ($)</Label>
          <Input type="number" value={balance} onChange={(e) => setBalance(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Spread (pips)</Label>
          <Input type="number" step="0.1" value={spread} onChange={(e) => setSpread(e.target.value)} />
        </div>
      </div>

      <div className="space-y-1">
        <Label>Execution Mode</Label>
        <Select value={mode} onValueChange={(v) => setMode(v as "close_price" | "intra_candle")}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="close_price">Close Price</SelectItem>
            <SelectItem value="intra_candle">Intra-Candle + Spread</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label>LLM Max Calls</Label>
          <Input type="number" value={maxLlm} onChange={(e) => setMaxLlm(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Volume (lots)</Label>
          <Input type="number" step="0.01" value={volume} onChange={(e) => setVolume(e.target.value)} />
        </div>
      </div>

      <div className="space-y-1">
        <Label>CSV Data (optional, overrides MT5)</Label>
        <Input
          type="file"
          accept=".csv"
          onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
          className="cursor-pointer"
        />
        <p className="text-xs text-muted-foreground">
          CSV columns: time, open, high, low, close, tick_volume
        </p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Button type="submit" className="w-full" disabled={submitting}>
        {uploading ? "Uploading CSV..." : submitting ? "Submitting..." : "Run Backtest"}
      </Button>
    </form>
  );
}
```

**Step 2: Create `frontend/src/components/backtest/backtest-run-list.tsx`**

```typescript
"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { BacktestRunSummary } from "@/types/trading";

interface Props {
  runs: BacktestRunSummary[];
  selectedRunId: number | null;
  onSelect: (run: BacktestRunSummary) => void;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

export function BacktestRunList({ runs, selectedRunId, onSelect }: Props) {
  if (runs.length === 0) {
    return <p className="text-sm text-muted-foreground py-4 text-center">No runs yet</p>;
  }

  return (
    <ul className="space-y-1">
      {runs.map((run) => (
        <li key={run.id}>
          <button
            onClick={() => onSelect(run)}
            className={cn(
              "w-full text-left rounded-md px-3 py-2 text-sm hover:bg-accent transition-colors",
              selectedRunId === run.id && "bg-accent",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium truncate">
                {run.symbol} · {run.timeframe}
              </span>
              <span className={cn("text-xs px-1.5 py-0.5 rounded font-medium", STATUS_COLORS[run.status])}>
                {run.status}
              </span>
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {run.start_date.slice(0, 10)} → {run.end_date.slice(0, 10)}
            </div>
            {run.status === "running" && (
              <div className="mt-1 h-1 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${run.progress_pct}%` }}
                />
              </div>
            )}
            {run.status === "completed" && run.total_return_pct != null && (
              <div className={cn("text-xs font-medium mt-0.5", run.total_return_pct >= 0 ? "text-green-600" : "text-red-600")}>
                {run.total_return_pct >= 0 ? "+" : ""}{run.total_return_pct.toFixed(2)}%
              </div>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
```

**Step 3: Create `frontend/src/components/backtest/backtest-metrics-grid.tsx`**

```typescript
import type { BacktestRunSummary } from "@/types/trading";

interface Props { run: BacktestRunSummary; }

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-lg border bg-card p-3 text-center">
      <div className={`text-lg font-bold ${color ?? ""}`}>{value}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
    </div>
  );
}

function fmt(v: number | null | undefined, decimals = 2, suffix = ""): string {
  if (v == null) return "—";
  return `${v.toFixed(decimals)}${suffix}`;
}

export function BacktestMetricsGrid({ run }: Props) {
  const pnlColor = (run.total_return_pct ?? 0) >= 0 ? "text-green-600" : "text-red-600";
  return (
    <div className="grid grid-cols-4 gap-2">
      <MetricCard label="Total Return" value={fmt(run.total_return_pct, 2, "%")} color={pnlColor} />
      <MetricCard label="Win Rate" value={fmt(run.win_rate ? run.win_rate * 100 : null, 1, "%")} />
      <MetricCard label="Profit Factor" value={fmt(run.profit_factor)} />
      <MetricCard label="Max Drawdown" value={fmt(run.max_drawdown_pct, 2, "%")} color="text-red-500" />
      <MetricCard label="Recovery Factor" value={fmt(run.recovery_factor)} />
      <MetricCard label="Sharpe Ratio" value={fmt(run.sharpe_ratio)} />
      <MetricCard label="Sortino Ratio" value={fmt(run.sortino_ratio)} />
      <MetricCard label="Expectancy" value={fmt(run.expectancy, 2, "$")} />
      <MetricCard label="Total Trades" value={String(run.total_trades ?? "—")} />
      <MetricCard label="Avg Win" value={fmt(run.avg_win, 2, "$")} color="text-green-600" />
      <MetricCard label="Avg Loss" value={fmt(run.avg_loss, 2, "$")} color="text-red-500" />
      <MetricCard label="Max Consec Wins" value={String(run.max_consec_wins ?? "—")} />
    </div>
  );
}
```

**Step 4: Create `frontend/src/components/backtest/equity-curve-chart.tsx`**

```typescript
"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BacktestEquityPoint } from "@/types/trading";

interface Props { data: BacktestEquityPoint[]; initialBalance: number; }

export function EquityCurveChart({ data, initialBalance }: Props) {
  if (data.length === 0) return <p className="text-sm text-muted-foreground text-center py-8">No trade data</p>;

  const chartData = [
    { time: data[0].time.slice(0, 10), equity: initialBalance },
    ...data.map((d) => ({ time: d.time.slice(0, 10), equity: d.equity })),
  ];

  const minEquity = Math.min(...chartData.map((d) => d.equity));
  const maxEquity = Math.max(...chartData.map((d) => d.equity));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={chartData} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.2} />
            <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="time" tick={{ fontSize: 10 }} tickLine={false}
          tickFormatter={(v: string) => v.slice(0, 7)} />
        <YAxis domain={[minEquity * 0.99, maxEquity * 1.01]} tick={{ fontSize: 10 }} tickLine={false}
          tickFormatter={(v: number) => `$${v.toLocaleString()}`} />
        <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, "Equity"]}
          labelStyle={{ fontSize: 11 }} contentStyle={{ fontSize: 11 }} />
        <Area type="monotone" dataKey="equity" stroke="hsl(var(--primary))"
          fill="url(#equityGradient)" strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
```

**Step 5: Create `frontend/src/components/backtest/monthly-heatmap.tsx`**

```typescript
"use client";

import { cn } from "@/lib/utils";
import type { BacktestMonthlyPnl } from "@/types/trading";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

interface Props { data: BacktestMonthlyPnl[]; }

export function MonthlyHeatmap({ data }: Props) {
  if (data.length === 0) return <p className="text-sm text-muted-foreground text-center py-4">No monthly data</p>;

  const years = [...new Set(data.map((d) => d.year))].sort();
  const byKey = new Map(data.map((d) => [`${d.year}-${d.month}`, d]));

  const maxAbs = Math.max(...data.map((d) => Math.abs(d.pnl)), 1);

  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className="w-10 text-left text-muted-foreground pr-2">Year</th>
            {MONTHS.map((m) => <th key={m} className="w-10 text-center text-muted-foreground">{m}</th>)}
          </tr>
        </thead>
        <tbody>
          {years.map((year) => (
            <tr key={year}>
              <td className="pr-2 text-muted-foreground font-medium">{year}</td>
              {MONTHS.map((_, mi) => {
                const entry = byKey.get(`${year}-${mi + 1}`);
                const pnl = entry?.pnl ?? null;
                const intensity = pnl != null ? Math.min(Math.abs(pnl) / maxAbs, 1) : 0;
                const bg = pnl == null
                  ? "bg-muted/30"
                  : pnl > 0
                  ? `bg-green-${Math.round(intensity * 4 + 1) * 100 > 900 ? 900 : Math.round(intensity * 4 + 1) * 100}`
                  : `bg-red-${Math.round(intensity * 4 + 1) * 100 > 900 ? 900 : Math.round(intensity * 4 + 1) * 100}`;
                return (
                  <td key={mi}
                    title={pnl != null ? `${year}-${MONTHS[mi]}: $${pnl.toFixed(2)} (${entry?.trade_count} trades)` : "No trades"}
                    className={cn("w-10 h-7 rounded text-center cursor-default", bg)}
                  >
                    {pnl != null && (
                      <span className={cn("text-[9px] font-medium", pnl >= 0 ? "text-green-900" : "text-red-900")}>
                        {pnl >= 0 ? "+" : ""}{pnl.toFixed(0)}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

**Step 6: Create `frontend/src/components/backtest/backtest-trade-table.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { BacktestTrade } from "@/types/trading";

interface Props { trades: BacktestTrade[]; }

export function BacktestTradeTable({ trades }: Props) {
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;
  const totalPages = Math.ceil(trades.length / PAGE_SIZE);
  const slice = trades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (trades.length === 0) return <p className="text-sm text-muted-foreground text-center py-4">No trades</p>;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50">
            <tr>
              {["#", "Symbol", "Dir", "Entry Time", "Entry", "Exit", "SL", "TP", "P&L", "Exit"].map((h) => (
                <th key={h} className="px-2 py-1.5 text-left font-medium text-muted-foreground">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((t, i) => (
              <tr key={t.id} className={cn("border-t", i % 2 === 0 ? "" : "bg-muted/20")}>
                <td className="px-2 py-1 text-muted-foreground">{page * PAGE_SIZE + i + 1}</td>
                <td className="px-2 py-1 font-medium">{t.symbol}</td>
                <td className={cn("px-2 py-1 font-bold", t.direction === "BUY" ? "text-green-600" : "text-red-600")}>
                  {t.direction}
                </td>
                <td className="px-2 py-1 text-muted-foreground">{t.entry_time.slice(0, 16)}</td>
                <td className="px-2 py-1">{t.entry_price.toFixed(5)}</td>
                <td className="px-2 py-1">{t.exit_price?.toFixed(5) ?? "—"}</td>
                <td className="px-2 py-1 text-red-500">{t.stop_loss.toFixed(5)}</td>
                <td className="px-2 py-1 text-green-600">{t.take_profit.toFixed(5)}</td>
                <td className={cn("px-2 py-1 font-medium", (t.profit ?? 0) >= 0 ? "text-green-600" : "text-red-600")}>
                  {t.profit != null ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}` : "—"}
                </td>
                <td className="px-2 py-1 text-muted-foreground capitalize">{t.exit_reason ?? "open"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{trades.length} total trades</span>
          <div className="flex gap-1">
            <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>←</Button>
            <span className="px-2 py-1">{page + 1} / {totalPages}</span>
            <Button variant="outline" size="sm" onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}>→</Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 7: Create `frontend/src/components/backtest/backtest-results.tsx`**

```typescript
"use client";

import { useEffect, useState } from "react";
import { backtestApi } from "@/lib/api";
import type { BacktestRunSummary, BacktestTrade, BacktestEquityPoint, BacktestMonthlyPnl } from "@/types/trading";
import { BacktestMetricsGrid } from "./backtest-metrics-grid";
import { EquityCurveChart } from "./equity-curve-chart";
import { MonthlyHeatmap } from "./monthly-heatmap";
import { BacktestTradeTable } from "./backtest-trade-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface Props { run: BacktestRunSummary; }

export function BacktestResults({ run }: Props) {
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [equity, setEquity] = useState<BacktestEquityPoint[]>([]);
  const [monthly, setMonthly] = useState<BacktestMonthlyPnl[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (run.status !== "completed") return;
    setLoading(true);
    Promise.all([
      backtestApi.getTrades(run.id, { limit: 1000 }),
      backtestApi.getEquityCurve(run.id),
      backtestApi.getMonthlyPnl(run.id),
    ])
      .then(([t, e, m]) => { setTrades(t); setEquity(e); setMonthly(m); })
      .finally(() => setLoading(false));
  }, [run.id, run.status]);

  if (run.status === "pending" || run.status === "running") {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="text-center">
          <p className="text-lg font-medium">
            {run.status === "pending" ? "Backtest queued..." : "Running backtest..."}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            {run.symbol} · {run.timeframe} · {run.start_date.slice(0, 10)} → {run.end_date.slice(0, 10)}
          </p>
        </div>
        <div className="w-64 h-2 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: `${run.progress_pct}%` }}
          />
        </div>
        <p className="text-sm text-muted-foreground">{run.progress_pct}%</p>
      </div>
    );
  }

  if (run.status === "failed") {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center text-destructive">
          <p className="font-medium">Backtest failed</p>
          <p className="text-sm mt-1">{run.error_message ?? "Unknown error"}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-sm mb-2">Summary Metrics</h3>
        <BacktestMetricsGrid run={run} />
      </div>

      <Tabs defaultValue="equity">
        <TabsList className="text-xs">
          <TabsTrigger value="equity">Equity Curve</TabsTrigger>
          <TabsTrigger value="monthly">Monthly P&L</TabsTrigger>
          <TabsTrigger value="trades">Trade List ({run.total_trades ?? 0})</TabsTrigger>
        </TabsList>

        <TabsContent value="equity" className="mt-2">
          <EquityCurveChart data={equity} initialBalance={run.initial_balance} />
        </TabsContent>

        <TabsContent value="monthly" className="mt-2">
          <MonthlyHeatmap data={monthly} />
        </TabsContent>

        <TabsContent value="trades" className="mt-2">
          <BacktestTradeTable trades={trades} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

**Step 8: Commit all components**

```bash
git add frontend/src/components/backtest/
git commit -m "feat(backtest): add all backtest UI components (config form, metrics, charts, trade table)"
```

---

## Task 9: Frontend — Backtest Page + Sidebar

**Files:**

- Create: `frontend/src/app/backtest/page.tsx`
- Modify: `frontend/src/components/app-sidebar.tsx`

**Step 1: Create `frontend/src/app/backtest/page.tsx`**

```typescript
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BacktestConfigForm } from "@/components/backtest/backtest-config-form";
import { BacktestRunList } from "@/components/backtest/backtest-run-list";
import { BacktestResults } from "@/components/backtest/backtest-results";
import { backtestApi } from "@/lib/api";
import { API_BASE_URL } from "@/lib/api";
import type { BacktestRunSummary } from "@/types/trading";

// Static strategies list from backend
interface StrategyItem { id: number; name: string; timeframe: string; strategy_type: string; }

export default function BacktestPage() {
  const [runs, setRuns] = useState<BacktestRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<BacktestRunSummary | null>(null);
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const refreshRuns = useCallback(async () => {
    const latest = await backtestApi.listRuns({ limit: 50 });
    setRuns(latest);
    // Update selectedRun if it changed
    if (selectedRun) {
      const updated = latest.find((r) => r.id === selectedRun.id);
      if (updated) setSelectedRun(updated);
    }
  }, [selectedRun]);

  useEffect(() => {
    // Load strategies for the config form
    fetch(`${API_BASE_URL}/api/v1/strategies`)
      .then((r) => r.json())
      .then((data: StrategyItem[]) => setStrategies(data))
      .catch(() => {});

    refreshRuns();

    // WebSocket for live progress updates
    const ws = new WebSocket(`${API_BASE_URL.replace("http", "ws")}/ws/dashboard/0`);
    wsRef.current = ws;
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as { event: string; data: unknown };
      if (["backtest_progress", "backtest_complete", "backtest_failed"].includes(msg.event)) {
        refreshRuns();
      }
    };
    return () => ws.close();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleRunCreated = (run: BacktestRunSummary) => {
    setRuns((prev) => [run, ...prev]);
    setSelectedRun(run);
  };

  // Poll while any run is active
  useEffect(() => {
    const hasActive = runs.some((r) => r.status === "pending" || r.status === "running");
    if (!hasActive) return;
    const id = setInterval(refreshRuns, 3000);
    return () => clearInterval(id);
  }, [runs, refreshRuns]);

  return (
    <div className="flex h-full">
      {/* Left panel: Config + Run History */}
      <div className="w-80 shrink-0 border-r flex flex-col h-full overflow-hidden">
        <div className="p-4 border-b">
          <h1 className="text-base font-semibold">Strategy Tester</h1>
          <p className="text-xs text-muted-foreground mt-0.5">Backtest on historical OHLCV data</p>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          <BacktestConfigForm strategies={strategies} onRunCreated={handleRunCreated} />

          <div>
            <h2 className="text-sm font-medium mb-2">Past Runs</h2>
            <BacktestRunList
              runs={runs}
              selectedRunId={selectedRun?.id ?? null}
              onSelect={setSelectedRun}
            />
          </div>
        </div>
      </div>

      {/* Right panel: Results */}
      <div className="flex-1 overflow-y-auto p-6">
        {selectedRun ? (
          <BacktestResults key={selectedRun.id} run={selectedRun} />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <div className="text-center">
              <p className="text-lg font-medium">Select or run a backtest</p>
              <p className="text-sm mt-1">Configure a strategy and date range on the left, then click Run.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Add "Backtest" nav item to sidebar**

In `frontend/src/components/app-sidebar.tsx`:

Add `FlaskConical` to the lucide-react import:

```typescript
import {
  BarChart3,
  Brain,
  Cpu,
  FlaskConical,
  LayoutDashboard,
  ScrollText,
  Settings,
  Shield,
  TrendingUp,
  Users,
} from "lucide-react";
```

Add to the `navItems` array (after Pipeline Logs):

```typescript
{ title: "Backtest", url: "/backtest", icon: FlaskConical },
```

**Step 3: Verify frontend builds**

```bash
cd frontend
npm run dev
```

Navigate to `http://localhost:3000/backtest` — the page should render with the config form and empty run history.

**Step 4: Commit**

```bash
git add frontend/src/app/backtest/ frontend/src/components/app-sidebar.tsx
git commit -m "feat(backtest): add /backtest page and sidebar nav item"
```

---

## Task 10: End-to-End Smoke Test

**Step 1: Ensure backend is running**

```bash
cd backend
docker compose up -d postgres questdb
uv run alembic upgrade head
uv run uvicorn main:app --reload --port 8000
```

**Step 2: Run all backend tests**

```bash
cd backend
uv run pytest tests/test_backtest_metrics.py tests/test_backtest_data.py tests/test_backtest_engine.py -v
```

Expected: all tests pass.

**Step 3: Submit a CSV backtest via curl**

Download or prepare a small CSV test file with 200 rows (EURUSD M15), then:

```bash
# Upload CSV
curl -X POST http://localhost:8000/api/v1/backtest/data/upload \
  -F "file=@test_eurusd.csv"
# Note the upload_id from response

# Submit backtest run (replace upload_id and strategy_id)
curl -X POST http://localhost:8000/api/v1/backtest/runs \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": 1,
    "symbol": "EURUSD",
    "start_date": "2020-01-01T00:00:00Z",
    "end_date": "2020-02-01T00:00:00Z",
    "csv_upload_id": "/tmp/xxxx.csv",
    "execution_mode": "close_price"
  }'
```

Expected: `202 Accepted` with `{"status": "pending", ...}`.

**Step 4: Poll until completed**

```bash
curl http://localhost:8000/api/v1/backtest/runs/1
```

Expected: `{"status": "completed", "total_trades": N, "win_rate": ...}`

**Step 5: Final commit**

```bash
git add .
git commit -m "feat(backtest): complete backtest system — engine, API, and dashboard page"
```

---

## Recharts Dependency Check

Before Task 8, verify Recharts is already installed (it's used in Analytics page):

```bash
grep -r "recharts" frontend/package.json
```

If not found, install it:

```bash
cd frontend && npm install recharts
```

---

## Summary of New Files

**Backend:**

- `backend/db/models.py` — `BacktestRun` + `BacktestTrade` models added
- `backend/alembic/versions/xxxx_add_backtest_tables.py` — migration (auto-generated)
- `backend/services/backtest_metrics.py` — pure-Python metrics computation
- `backend/services/backtest_data.py` — MT5 + CSV data loading
- `backend/services/backtest_engine.py` — event-loop simulation engine
- `backend/api/routes/backtest.py` — HTTP endpoints
- `backend/tests/test_backtest_metrics.py`
- `backend/tests/test_backtest_data.py`
- `backend/tests/test_backtest_engine.py`

**Frontend:**

- `frontend/src/types/trading.ts` — backtest types appended
- `frontend/src/lib/api.ts` — `backtestApi` appended
- `frontend/src/components/backtest/backtest-config-form.tsx`
- `frontend/src/components/backtest/backtest-run-list.tsx`
- `frontend/src/components/backtest/backtest-metrics-grid.tsx`
- `frontend/src/components/backtest/equity-curve-chart.tsx`
- `frontend/src/components/backtest/monthly-heatmap.tsx`
- `frontend/src/components/backtest/backtest-trade-table.tsx`
- `frontend/src/components/backtest/backtest-results.tsx`
- `frontend/src/app/backtest/page.tsx`
