# Plan 06: LLM Cost + P&L Attribution Reporting

**Branch:** `feature/cost-pnl-tracking`
**Depends on:** 01 (needs `trades.source` to exclude manual trades from
AI-cost-attributed P&L).
**Risk:** low — additive reporting, no decision-path changes.

## Goal

`llm_calls` already tracks per-call token cost (`_extract_tokens()`,
`compute_cost()`, `LLM_PRICING`). Nothing joins that cost back to realized
trade P&L. Add "net of AI cost" profitability so it's visible whether a
strategy is actually profitable once LLM spend is netted out.

## Steps

1. Confirm the existing link path: `llm_calls` → `pipeline_runs` →
   (via `AIJournal.trade_id` or equivalent) → `trades`. If the join chain
   is incomplete anywhere (e.g. `pipeline_runs` doesn't currently carry a
   `trade_id` once a trade is opened), add the missing FK rather than
   inferring the link by timestamp proximity.
2. Add a query/service function: for a given symbol/strategy/account and
   date range, sum `trades.profit` (realized P&L) minus sum of
   `llm_calls.cost` for every call attributed to that trade's pipeline
   run(s) — include maintenance-pipeline calls (`review_position()`) for
   trades that were held and re-evaluated, not just the entry decision.
3. Surface on the existing LLM analytics dashboard
   (`api/routes/llm_analytics`) as a new column/panel: "Realized P&L",
   "LLM Cost", "Net P&L", grouped by symbol and by strategy.
4. Only include `trades.source = "ai"` rows (from plan 01) in the
   AI-cost-attributed calculation — manual trades have no attributable
   LLM cost and shouldn't be netted against it, but should probably still
   appear in a separate "manual trades P&L" figure for the user's own
   tracking, since this account mixes both.

## Acceptance criteria

- Dashboard shows Net P&L (realized minus attributed LLM cost) per symbol
  and per strategy.
- Manual trades are excluded from LLM-cost attribution but still visible
  in overall account P&L.
- `uv run pytest -v` passes; add a test for the join/aggregation logic
  with a small fixture (2-3 trades, known LLM call costs, assert the
  computed net P&L).

## Post-implementation note (what already existed vs. what was built)

### The join chain already existed — no migration needed

Step 1's concern was unfounded: `pipeline_runs.trade_id` (FK to
`trades.id`) already exists (`db/models.py:210-212`), as does
`pipeline_steps.run_id` and `llm_calls.pipeline_step_id`. The full chain
`llm_calls → pipeline_steps → pipeline_runs → trades` was already usable
without any schema change.

### Most of "the dashboard" already existed too — this plan was narrower than written

`api/routes/llm_analytics/_performance.py` already had extensive cost/P&L
analytics before this branch: `/model-performance` (per-model win rate,
total P&L, cost, profit-per-dollar ROI), `/summary`, `/heatmap`
(model×symbol win rate), `/pnl-timeline`, `/cost-trend`, and `/pipelines`
(per analysis/execution-model-pair P&L and cost split). The "add cost/P&L
reporting" premise was mostly already delivered — just not sliced by
**symbol** or **strategy**, and always scoped to `task_type == "signal"`
only (excluding maintenance-pipeline LLM cost).

### What was actually added

- **New endpoint** `GET /llm-analytics/symbol-pnl?days=&group_by=symbol|source`
  (`_performance.py`) — the one genuinely missing slice: net P&L after
  attributed LLM cost, grouped by symbol or by `Trade.source` (which
  already doubles as "strategy" — see plan 01's finding: `source` holds
  `"ai"` | `"manual"` | a strategy class name). Unlike the existing
  endpoints, this one does **not** filter to `task_type == "signal"` — it
  deliberately includes maintenance-pipeline LLM calls tied to a trade via
  the same `pipeline_runs.trade_id` FK, per this plan's own step 2.
- Manual-trade exclusion (step 4) — structurally, a manual trade never has
  a `pipeline_runs` row pointing at it in the first place (nothing creates
  one for a manually-placed order), so the outer join naturally yields
  `cost_usd = NULL` for it. The aggregation still explicitly checks
  `Trade.source == "manual"` as a defensive second layer (in case a
  pipeline run ever got mis-attributed to a manual trade) and tracks its
  P&L separately (`manual_trade_count`/`manual_pnl_usd`), never netted
  against LLM cost.
- Frontend: new `SymbolPnLTable` component + a "P&L Attribution" tab on
  `/llm-analytics`, with a By Symbol / By Strategy toggle, sortable
  columns (AI Trades, Realized P&L, LLM Cost, Net P&L, Manual Trades,
  Manual P&L), consistent with the existing `ModelPerformanceTable`
  styling.
- `tests/test_symbol_pnl.py` (new, 6 tests) — dedup-profit-sum-cost across
  multiple llm_calls rows for one trade (covers the maintenance-calls
  case), manual-trade exclusion, grouping by symbol vs. source, sort
  order, empty-input handling. This was the first test file for the
  `llm_analytics` route package — none existed before.

### Not verified (needs real trade/LLM-call history)

- The aggregation is unit-tested with synthetic rows; the actual query
  (`_fetch_symbol_pnl_rows`) needs a real Postgres instance with trade +
  pipeline_run + llm_calls data to confirm the outer-join SQL behaves as
  expected — not exercised against a live DB in this session.
- `npm run build` still can't run in this sandbox (Node 18.19.1 vs.
  Next.js 16's required ≥20.9.0 — the same pre-existing sandbox
  limitation plan 02 first hit). Verified via `npm run lint` (+1 warning,
  0 new errors, confirmed against the unmodified tree) and
  `npx tsc --noEmit` (no new errors) instead — re-run a real
  `npm run build` in the Node 20+ dev/CI environment before merging.
