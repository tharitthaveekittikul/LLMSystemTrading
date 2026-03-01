# Pipeline Logs — Design Document

**Date:** 2026-03-01
**Status:** Approved
**Goal:** Full audit traceability for every AI trading pipeline run — stored in PostgreSQL, visualised as a step-by-step timeline in the dashboard, with live WebSocket updates.

---

## Problem

The existing `ai_journal` table captures *what the AI decided* (signal, confidence, rationale) but nothing about *how the pipeline ran*: which steps executed, how long each took, what data was sent to the LLM, what the raw response was, whether the kill switch fired, whether Telegram sent. There is no way to audit an abnormal run after the fact.

---

## Chosen Approach: Two Tables (A)

`pipeline_runs` (parent) + `pipeline_steps` (children). Normalised, queryable per step, extensible.

Rejected alternatives:
- **Single JSON column** — can't query step outcomes; JSON grows large.
- **Extend AIJournal** — breaks single responsibility; can't capture pre-LLM failures (rate limit kills the run before any journal row exists).

---

## Data Model

### `pipeline_runs`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| account_id | Integer FK → accounts | |
| symbol | String(20) | e.g. "EURUSD" |
| timeframe | String(10) | e.g. "M15" |
| status | String(20) | `running` \| `completed` \| `hold` \| `skipped` \| `failed` |
| final_action | String(10) nullable | `BUY` \| `SELL` \| `HOLD` |
| total_duration_ms | Integer nullable | Set on completion |
| journal_id | Integer FK → ai_journal nullable | Linked after LLM step |
| trade_id | Integer FK → trades nullable | Linked after MT5 execution |
| created_at | DateTime(tz) | |

### `pipeline_steps`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| run_id | Integer FK → pipeline_runs | Cascade delete |
| seq | Integer | Ordering (1, 2, 3…) |
| step_name | String(50) | See table below |
| status | String(10) | `ok` \| `skip` \| `error` |
| input_json | Text nullable | JSON string |
| output_json | Text nullable | JSON string |
| error | Text nullable | Error message if status=error |
| duration_ms | Integer | |

### Steps recorded per run

| seq | step_name | input | output |
|-----|-----------|-------|--------|
| 1 | `account_loaded` | `{account_id}` | `{name, auto_trade_enabled, max_lot_size}` |
| 2 | `rate_limit_check` | `{account_id}` | `{allowed: bool}` |
| 3 | `ohlcv_fetch` | `{symbol, timeframe}` | `{source: cache\|mt5, candle_count, current_price}` |
| 4 | `indicators_computed` | `{candle_count}` | `{sma_20, recent_high, recent_low}` |
| 5 | `positions_fetched` | `{account_id}` | `[{symbol, direction, volume, profit}]` |
| 6 | `signals_fetched` | `{account_id, symbol}` | `[{signal, confidence, rationale}]` |
| 7 | `llm_analyzed` | full prompt text | raw `TradingSignal` JSON + provider + model |
| 8 | `confidence_gate` | `{confidence, threshold}` | `{action_before, action_after}` |
| 9 | `journal_saved` | — | `{journal_id}` |
| 10 | `kill_switch_check` | — | `{active: bool}` |
| 11 | `order_built` | `{symbol, direction, volume, entry, sl, tp}` | — |
| 12 | `mt5_executed` | — | `{ticket, success, error}` |
| 13 | `telegram_sent` | — | `{sent: bool, message_preview}` |

> Full 50-candle OHLCV array is NOT stored in steps (too large). `ohlcv_fetch` stores summary only. The full prompt in step 7 (`llm_analyzed`) includes the last 20 candles the LLM actually received.

---

## Backend Architecture

### `services/pipeline_tracer.py` (new file)

Async context manager wrapping a pipeline run:

```python
async with PipelineTracer(db, account_id, symbol, timeframe) as tracer:
    await tracer.record("account_loaded", input={...}, output={...}, duration_ms=12)
    await tracer.record("llm_analyzed", input={"prompt": full_prompt}, output=signal.dict(), duration_ms=890)
    tracer.finalize(status="completed", final_action="BUY", journal_id=42, trade_id=7)
```

- `__aenter__`: inserts `pipeline_runs` row with status `running`
- `record()`: inserts one `pipeline_steps` row immediately (partial steps survive crashes)
- `__aexit__`: updates run row to final status + `total_duration_ms`
- On unhandled exception: status → `failed`, error written to last step

### Instrumentation of `services/ai_trading.py`

Wrap each of the 13 steps with `tracer.record(...)`. Pipeline logic is unchanged — only timing and recording are added. The `orchestrator.analyze_market()` function returns the formatted prompt string alongside the signal so it can be captured in step 7.

### New API routes — `api/routes/pipeline.py`

```
GET /api/v1/pipeline/runs
    ?account_id=  &symbol=  &status=  &limit=50  &offset=0
    → list[PipelineRunSummary]  (no steps)

GET /api/v1/pipeline/runs/{run_id}
    → PipelineRunDetail  (run + all steps ordered by seq)
```

Registered in `main.py` alongside existing routers.

### WebSocket event

On run completion, `PipelineTracer` broadcasts on the existing account channel:

```json
{
  "event": "pipeline_run_complete",
  "data": {
    "run_id": 42,
    "symbol": "EURUSD",
    "timeframe": "M15",
    "status": "completed",
    "final_action": "BUY",
    "total_duration_ms": 1240,
    "step_count": 13
  }
}
```

---

## Frontend Architecture

### New page: `app/logs/page.tsx`

Two-panel layout:
- **Left panel** — `PipelineRunsList`: filterable list of runs, live-updated via WebSocket
- **Right panel** — `PipelineRunDetail`: step timeline for selected run

### New files

| File | Purpose |
|------|---------|
| `app/logs/page.tsx` | Page route |
| `components/logs/pipeline-runs-list.tsx` | Left panel — list + filter + live WS |
| `components/logs/pipeline-run-detail.tsx` | Right panel — step timeline |
| `components/logs/pipeline-step-card.tsx` | Single expandable step row |
| `lib/api.ts` | Add `logsApi.listRuns()` and `logsApi.getRun(id)` |
| `types/trading.ts` | Add `PipelineRun`, `PipelineStep` types |

### Sidebar

Add **"Pipeline Logs"** nav item to `app-sidebar.tsx` pointing to `/logs`.

### Behaviour

- On mount: fetch last 50 runs via `GET /api/v1/pipeline/runs`
- New runs: stream in via WebSocket `pipeline_run_complete` → prepend with highlight flash
- Click a run: fetch `GET /api/v1/pipeline/runs/{id}` → render step timeline
- Step cards: collapsed by default (name + status badge + duration). Click ▶ to expand input/output as pretty-printed JSON.
- Filter bar: account selector + symbol text + status dropdown (all / BUY / SELL / HOLD / failed)

### Status colours

| Status | Colour |
|--------|--------|
| `ok` | Green |
| `skip` | Yellow |
| `error` | Red |
| `running` | Blue pulse |

---

## Alembic Migration

```bash
uv run alembic revision --autogenerate -m "add pipeline_runs and pipeline_steps"
uv run alembic upgrade head
```

---

## Out of Scope

- Per-step live streaming (steps appear one-by-one as they execute). The full run is ~1-2 seconds; run-complete notification is sufficient.
- Storing full 50-candle OHLCV in steps.
- Retention/cleanup policy for old runs (can be added later).
