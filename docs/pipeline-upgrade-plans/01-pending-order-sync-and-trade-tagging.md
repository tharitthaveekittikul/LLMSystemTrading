# Plan 01: Pending-Order Sync + Manual/AI Trade Tagging

**Branch:** `feature/pending-order-sync`
**Depends on:** nothing — do this first.
**Risk:** medium — touches order state reconciliation on a live-money path.

## Goal

1. Automatically reconcile MT5 pending/open/closed order state against the
   `trades` table — no more waiting for the next maintenance sweep or a
   manual check to notice a filled/cancelled/closed order.
2. Distinguish AI-originated trades from manually-placed trades on the same
   account, since the user trades manually on the same account this system
   trades.

## Part A — Positive AI-trade tagging (do this first, it's a prerequisite for reconciliation)

Right now there's no way to *positively* identify an AI trade — you'd have
to infer it by "exists in `trades` table" vs "doesn't," which breaks the
moment reconciliation needs to run in the other direction (MT5 → DB).

1. Add a `source` column to the `trades` table: enum `ai` | `manual`.
   Alembic migration, backfill existing rows as `ai` (this system has only
   placed AI trades to date — confirm this assumption against row count
   before backfilling).
2. In `services/ai_trading/_execution.py` (or wherever `order_send()` is
   called for AI trades), set a distinguishing `comment` on the MT5 order
   (e.g. `"AI"` — MT5 comment fields are short, keep it under ~20 chars) or
   a dedicated `magic` number range reserved for AI trades. Store the same
   value in the new `trades.source` column at insert time.
3. Confirm with a demo/paper account: place one AI trade and one manual
   trade side by side, verify the `comment`/`magic` distinction actually
   shows up in `positions_get()`/`orders_get()` results (some MT5 brokers
   strip or ignore comments — verify before relying on it).

## Part B — Reconciliation loop

1. Extend `services/equity_poller.py`'s existing 60s per-account loop
   (already opens an MT5 connection per account) rather than adding a new
   poller — avoids a second concurrent MT5 connection per account, which
   would violate the single-thread-per-process MT5 constraint documented
   in `documents/mt5-python/connection.md`.
2. Each cycle, per account:
   - Fetch `positions_get()` and `orders_get()` (or equivalent bridge
     methods) — live MT5 state.
   - Diff against `trades` rows with `order_status in ("pending", "open")`.
   - **Filled**: pending order gone from MT5, appears as a position →
     update `trades.order_status = "open"`, set entry price/time from MT5.
   - **Closed**: open position gone from MT5 → update
     `trades.order_status = "closed"`, pull close price/time/profit from
     MT5 history (`history_deals_get()` or equivalent), trigger the
     existing post-trade analysis / research-loop-trigger path exactly as
     if the closing had been detected by `api/routes/accounts/_sync.py`
     (don't duplicate that trigger logic — call the same function).
   - **Cancelled/expired pending**: gone from MT5 with no matching
     position or close deal → update `trades.order_status = "cancelled"`.
   - **Untagged position/order found in MT5** (no matching `trades` row,
     or `source` tag reads as non-AI) → insert a `trades` row with
     `source = "manual"` so it shows up in position counts, risk checks
     (position limit, hedging), and the dashboard — this is required for
     `check_position_limit`/`check_hedging` to be aware of manually-opened
     exposure, otherwise the AI could size a new trade as if the manual
     position didn't exist.
3. Broadcast a WebSocket event (reuse the `positions_update` event type
   already listed in `api/routes/ws.py`) whenever reconciliation changes
   state, so the dashboard updates without a page refresh.

## Acceptance criteria

- A manually-placed trade on a demo account appears in the dashboard
  within one 60s poll cycle, tagged `manual`.
- An AI-placed limit order that fills on the broker side updates `trades`
  within one poll cycle, with no manual intervention.
- `check_position_limit`/`check_hedging` account for manually-opened
  positions in their counts (verify with a test: manually open a position
  up to the account's max, confirm the AI pipeline correctly reports
  position-limit-blocked on its next scheduled run).
- `uv run pytest -v` passes; add tests for the diff logic (filled/closed/
  cancelled/manual-detected cases) using a mocked MT5 bridge.
