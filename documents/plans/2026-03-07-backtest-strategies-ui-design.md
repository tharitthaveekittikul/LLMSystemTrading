# Design: Backtest CSV Fix, Strategies UI Overhaul & DB Cleanup

**Date**: 2026-03-07
**Status**: Approved

---

## Summary

Four independent improvements:
1. Fix CSV upload to accept MT5 tab-delimited format with per-candle spread
2. Update backtest page to display spread info
3. Overhaul strategies page: 5 execution modes, edit page, performance stats on cards
4. Python cleanup script for test data in `llm_calls` and related tables

---

## 1. CSV Upload Fix + Per-Candle Spread

### Root Cause
`BacktestDataService.load_from_csv()` (`backend/services/backtest_data.py`) calls `pd.read_csv()` with comma separator and expects plain column names (`time, open, high, low, close, tick_volume`). MT5 exports are **tab-delimited** with **angle-bracket headers** (`<DATE>`, `<TIME>`, `<OPEN>`, `<HIGH>`, `<LOW>`, `<CLOSE>`, `<TICKVOL>`, `<VOL>`, `<SPREAD>`).

### Fix
- Replace `load_from_csv()` to call `mtf_csv_loader.load_mt5_csv()` and convert `OHLCV` dataclasses to dicts, adding the `spread` field (integer points from `<SPREAD>` column).
- `OHLCV` dataclass in `mtf_data.py` gains an optional `spread: int = 0` field.
- `mtf_csv_loader.py` populates `spread` from the `<SPREAD>` column.

### Per-Candle Spread in BacktestEngine
- `BacktestEngine` currently applies a fixed `config["spread_pips"]` to every entry price.
- Update engine: if candle dict has `"spread"` key (non-zero), compute spread cost in price units using symbol pip value; otherwise fall back to `config["spread_pips"]`.
- Store average spread across all candles in the result dict and persist to `backtest_runs.avg_spread` (new nullable Float column via Alembic migration).

---

## 2. Backtest Page Updates

### BacktestConfigForm
- When a CSV is uploaded, hide the manual `spread_pips` input (spread comes per-candle).
- Show a read-only info line: `"Avg spread from CSV: ~X pts"` (computed by backend on upload, returned in upload response alongside `upload_id` and `size_bytes`).

### BacktestRunSummary (list card)
- Add a spread badge: `≈ X.X pts avg spread` alongside symbol/timeframe badges.

### BacktestResults panel (metrics grid)
- Add an "Avg Spread" row showing `avg_spread` from `BacktestRunSummary`.

### Backend
- `POST /backtest/data/upload` response: add `avg_spread_pts: float | None`.
- `BacktestRunSummary` schema: add `avg_spread: float | None`.
- Alembic migration: add `avg_spread` Float nullable column to `backtest_runs`.

---

## 3. Strategies Page Overhaul

### 3a. Strategy Cards — Performance Stats

Each card shows two stat sections:

**Backtest** (latest completed `backtest_run` for that `strategy_id`):
- Win rate, profit factor, total trades, run date
- "No backtest yet" if none

**Live** (aggregated from `trades` where `strategy_id = X` and `closed_at IS NOT NULL`):
- Total closed trades, win rate (profit > 0), total P&L
- "No live trades yet" if none

**Backend**: Add `GET /api/v1/strategies/{id}/stats` endpoint returning:
```json
{
  "backtest": { "win_rate": 0.62, "profit_factor": 1.8, "total_trades": 120, "run_date": "2026-03-01" } | null,
  "live": { "total_trades": 5, "win_rate": 0.6, "total_pnl": 245.0 } | null
}
```

**Frontend**: `StrategyCard` fetches stats from the new endpoint (or use a batch endpoint on list load to avoid N+1). Add stats section below existing badges.

### 3b. New Strategy Wizard — 5 Execution Modes

Replace the 3-type selector (`config / prompt / code`) with 5 execution modes:

| Mode | Description | Shows |
|------|-------------|-------|
| `llm_only` | LLM analyzes every candle | custom_prompt field |
| `rule_then_llm` | Rules filter, LLM validates signals | module_path + class_name |
| `rule_only` | Pure rules, zero LLM cost | module_path + class_name |
| `hybrid_validator` | Rules open trade, LLM validates afterward | module_path + class_name |
| `multi_agent` | Rules + LLM in parallel, consensus | module_path + class_name |

- DB: `execution_mode` column is already present. `strategy_type` is kept in DB but set automatically: `llm_only` → `strategy_type="prompt"`, code modes → `strategy_type="code"`.
- Frontend form sends `execution_mode` instead of `strategy_type`.

### 3c. Edit Strategy Page

- New page: `frontend/src/app/strategies/[id]/edit/page.tsx`
- Same 4-step wizard as New Strategy, pre-filled from `GET /api/v1/strategies/{id}`.
- On submit → `PATCH /api/v1/strategies/{id}`.
- All fields editable: name, description, execution_mode, symbols, timeframe, trigger, lot_size, sl_pips, tp_pips, custom_prompt, module_path, class_name, news_filter.
- "Edit" button on strategy cards and detail page links to `/strategies/{id}/edit`.
- `StrategyUpdate` backend schema already supports all fields.

---

## 4. Test Data Cleanup Script

**File**: `backend/scripts/cleanup_test_data.py`

Deletes known dev/test artifacts:
- `llm_calls` where `model` is a known test model name (e.g. `gpt-4o`, `gemini-2.5-flash`, `gemini-pro`, `gpt-3.5-turbo`)
- `pipeline_steps` linked to `pipeline_runs` with no `journal_id` and no `trade_id` (orphaned test runs)
- `pipeline_runs` that are orphaned (no account activity — test runs)

Prints a before/after count for each table. Safe to re-run (idempotent). Does **not** delete accounts, strategies, or backtest data.

Usage:
```bash
cd backend
uv run python scripts/cleanup_test_data.py
```

---

## Files Affected

### Backend
| File | Change |
|------|--------|
| `services/mtf_data.py` | Add `spread: int = 0` to `OHLCV` |
| `services/mtf_csv_loader.py` | Populate `spread` from `<SPREAD>` column |
| `services/backtest_data.py` | Replace `load_from_csv()` to call `mtf_csv_loader`, return spread |
| `services/backtest_engine.py` | Use per-candle spread; compute avg_spread in result |
| `api/routes/backtest.py` | Upload response + summary schema add `avg_spread`; persist to DB |
| `api/routes/strategies.py` | Add `GET /{id}/stats` endpoint; update `StrategyCreate`/`StrategyUpdate` for `execution_mode` |
| `db/models.py` | Add `avg_spread` to `BacktestRun` |
| `alembic/versions/XXXX_add_avg_spread.py` | Migration for `avg_spread` column |
| `scripts/cleanup_test_data.py` | New cleanup script |

### Frontend
| File | Change |
|------|--------|
| `components/backtest/backtest-config-form.tsx` | Hide spread input when CSV uploaded; show avg spread info |
| `components/backtest/backtest-metrics-grid.tsx` | Add Avg Spread row |
| `components/backtest/backtest-run-list.tsx` | Add spread badge to run cards |
| `types/trading.ts` | Add `avg_spread` to `BacktestRunSummary`; update `Strategy` type |
| `app/strategies/page.tsx` | Add stats section to each strategy card |
| `app/strategies/new/page.tsx` | Replace 3 types with 5 execution modes |
| `app/strategies/[id]/page.tsx` | Update Edit button link to `/strategies/[id]/edit` |
| `app/strategies/[id]/edit/page.tsx` | New edit page (4-step wizard pre-filled) |
| `lib/api/strategies.ts` | Add `getStats()` call |
