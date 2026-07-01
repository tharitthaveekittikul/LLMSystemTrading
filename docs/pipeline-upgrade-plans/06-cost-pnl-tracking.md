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
