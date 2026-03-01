# Backtest System Design
**Date:** 2026-03-01
**Status:** Approved

## Overview

Add a strategy backtesting system to LLMSystemTrading. Users select a strategy, a symbol, and a date range (default last 6 years), then the backend runs a simulation of the strategy on historical OHLCV data and returns comprehensive performance metrics.

---

## Requirements

| Requirement | Decision |
|---|---|
| Data source | MT5 `copy_rates_from` (primary) + CSV upload (fallback) |
| Date range | Configurable start/end (default: 6 years back to today) |
| LLM budget | Max N API calls per run (default 100, user-adjustable); evenly sampled across candles |
| Execution modes | Close-price fill OR intra-candle with spread simulation (user selects per run) |
| Compute | Backend Python async background job |
| Progress feedback | WebSocket broadcast every 1,000 candles + on completion |
| Metrics | Profit factor, expectancy, win rate, MDD, recovery factor, Sharpe, Sortino, total return, avg win/loss, max consecutive wins/losses, trade count |
| Charts | Equity curve (line), monthly P&L heatmap, per-trade P&L distribution histogram |
| Trade list | Paginated, filterable table of all simulated trades |
| Run history | Persistent — each run saved to DB, re-viewable at any time |

---

## Architecture

```
User submits config (POST /api/v1/backtest/runs)
        │
        ▼
FastAPI BackgroundTasks starts async job
BacktestRun row inserted (status=pending)
        │
        ▼
BacktestDataService
  ├── MT5 path: bridge.copy_rates_from(symbol, timeframe, start_date, end_date)
  └── CSV path: parse uploaded file (stored temporarily on disk)
        │
        ▼
BacktestEngine — per-candle event loop
  ├── Build rolling window → call strategy.generate_signal()
  ├── LLM strategies: sample every K-th candle (budget / total_candles)
  ├── Check open positions for SL/TP hit
  ├── Fill new orders (close_price OR intra_candle mode)
  ├── Record BacktestTrade rows in batches
  └── Broadcast ws event backtest_progress every 1,000 candles
        │
        ▼
BacktestMetrics computed from trade list
  → stored in BacktestRun row (status=completed)
  → broadcast ws event backtest_complete
        │
        ▼
Frontend /backtest page displays results
```

---

## Database Models

### `backtest_runs` table

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| strategy_id | int FK | references strategies.id |
| symbol | str | e.g. "EURUSD" |
| timeframe | str | "M15" |
| start_date | datetime | |
| end_date | datetime | |
| initial_balance | float | default 10,000 |
| spread_pips | float | default 1.5 |
| execution_mode | str | "close_price" \| "intra_candle" |
| max_llm_calls | int | 0 = rule-based forced; default 100 |
| status | str | pending \| running \| completed \| failed |
| progress_pct | int | 0–100 |
| error_message | str? | |
| total_trades | int | |
| win_rate | float | 0–1 |
| profit_factor | float | |
| expectancy | float | avg P&L per trade |
| max_drawdown_pct | float | |
| recovery_factor | float | total_return / max_drawdown |
| sharpe_ratio | float | |
| sortino_ratio | float | |
| total_return_pct | float | |
| avg_win | float | |
| avg_loss | float | |
| max_consec_wins | int | |
| max_consec_losses | int | |
| created_at | datetime | |

### `backtest_trades` table

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| run_id | int FK | references backtest_runs.id |
| symbol | str | |
| direction | str | BUY \| SELL |
| entry_time | datetime | |
| exit_time | datetime | |
| entry_price | float | |
| exit_price | float | |
| stop_loss | float | |
| take_profit | float | |
| volume | float | lots |
| profit | float | in account currency |
| exit_reason | str | "sl" \| "tp" \| "signal_reverse" \| "end_of_data" |
| equity_after | float | running portfolio equity (for equity curve) |

---

## API Routes (`/api/v1/backtest`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/runs` | Submit new backtest job; returns `{run_id}` immediately |
| GET | `/runs` | List all runs (summary metrics, status, config) |
| GET | `/runs/{id}` | Full run details + metrics |
| GET | `/runs/{id}/trades` | Paginated + filterable trade list |
| GET | `/runs/{id}/equity-curve` | `[{time, equity}]` array for line chart |
| DELETE | `/runs/{id}` | Delete run + associated trades |
| POST | `/data/upload` | Upload CSV file for a symbol/timeframe |

---

## Engine Logic

### Execution modes

**Close-price mode:**
- Signal at candle `N` close → fill at close price
- SL/TP checked at each subsequent candle's close

**Intra-candle mode:**
- Signal at candle `N` close → fill at next candle `N+1` open + spread
- SL/TP checked during candle: if candle's Low ≤ SL (for longs) → SL hit at SL price; if candle's High ≥ TP → TP hit
- If both SL and TP are within candle's range, the one closer to open price wins

### LLM budget

For LLM-type strategies:
- `step = total_candles / max_llm_calls`
- LLM called on candles `[0, step, 2*step, ...]`
- Between LLM calls: hold the last signal direction (no new entries, but monitor open positions)

### Strategy interface

Engine calls `strategy.generate_signal(ohlcv_df, open_positions)` — the same method signature as live trading. No strategy code changes required.

### Position management

- One position per symbol at a time (matching live behavior)
- Position closes on SL hit, TP hit, or opposing signal
- No partial closes

---

## Metrics Formulas

| Metric | Formula |
|---|---|
| Win Rate | `wins / total_trades` |
| Profit Factor | `gross_profit / abs(gross_loss)` |
| Expectancy | `(win_rate × avg_win) - (loss_rate × avg_loss)` |
| Max Drawdown | Max peak-to-trough decline in equity curve |
| Recovery Factor | `total_return / max_drawdown` |
| Sharpe Ratio | `mean(daily_returns) / std(daily_returns) × √252` |
| Sortino Ratio | `mean(daily_returns) / std(downside_returns) × √252` |
| Total Return | `(final_equity - initial_balance) / initial_balance` |

---

## WebSocket Events

| Event | Data |
|---|---|
| `backtest_progress` | `{run_id, progress_pct, candles_processed, equity}` |
| `backtest_complete` | `{run_id, status, metrics summary}` |
| `backtest_failed` | `{run_id, error_message}` |

---

## New Backend Files

| File | Purpose |
|---|---|
| `backend/services/backtest_engine.py` | Core event loop + order simulation |
| `backend/services/backtest_data.py` | Data fetching: MT5 + CSV parser |
| `backend/services/backtest_metrics.py` | All metrics computation |
| `backend/api/routes/backtest.py` | HTTP endpoints |
| `backend/db/models.py` | Add BacktestRun + BacktestTrade models |
| `backend/alembic/versions/xxxx_add_backtest_tables.py` | DB migration |

---

## New Frontend Files

| File | Purpose |
|---|---|
| `frontend/src/app/backtest/page.tsx` | Main backtest page |
| `frontend/src/components/backtest/backtest-config-form.tsx` | Left panel: config + run button |
| `frontend/src/components/backtest/backtest-run-list.tsx` | Left panel: past runs list |
| `frontend/src/components/backtest/backtest-results.tsx` | Right panel: metrics + charts |
| `frontend/src/components/backtest/equity-curve-chart.tsx` | Recharts line chart |
| `frontend/src/components/backtest/monthly-heatmap.tsx` | Monthly P&L calendar grid |
| `frontend/src/components/backtest/trade-distribution.tsx` | Recharts bar histogram |
| `frontend/src/components/backtest/backtest-trade-table.tsx` | Paginated trade list |
| `frontend/src/lib/api.ts` | Add `backtestApi` object |
| `frontend/src/types/trading.ts` | Add BacktestRun, BacktestTrade, BacktestMetrics types |

---

## Frontend Layout

```
/backtest
┌─────────────────────────┬────────────────────────────────────┐
│ Config (1/3)            │ Results (2/3)                       │
│                         │                                      │
│ Strategy: [dropdown]    │  Summary metrics grid (8 cards)     │
│ Symbol:   [text input]  │  Win Rate | Profit Factor | MDD     │
│ Start:    [date]        │  Recovery | Sharpe | Sortino        │
│ End:      [date]        │  Expectancy | Total Return           │
│ Balance:  [number]      │                                      │
│ Spread:   [pips]        │  Equity Curve (line chart)          │
│ Mode:     [radio]       │                                      │
│ LLM Max:  [number]      │  Monthly P&L Heatmap                │
│ [Upload CSV]            │                                      │
│ [Run Backtest]          │  Trade P&L Distribution             │
│                         │                                      │
│ ──────────────────────  │  Trade List Table                   │
│ Past Runs               │  (entry | exit | dir | P&L | exit_reason)
│ [clickable run list]    │                                      │
└─────────────────────────┴────────────────────────────────────┘
```

- Progress bar shown during active run (replaces results panel until complete)
- Clicking a past run in the list loads its results into the right panel
- CSV upload appears as drag-and-drop area below the symbol input
