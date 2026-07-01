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

## Post-implementation note (what already existed vs. what was built)

Before writing code, a sanity check (as this doc itself asked for — "confirm
this assumption") turned up two things this plan didn't know about:

1. **`trades.source` already existed** (`String(100), default="manual"`) —
   but with richer semantics than `ai`/`manual`: it holds `"ai"` (pure LLM
   trade, no strategy bound), a strategy class name (e.g.
   `"HarmonicStrategy"`), or the literal `"manual"` (set by
   `services/history_sync.py` when an MT5 deal has no matching `trades` row).
   A hardcoded MT5 `magic` number (`20250101`) and a `comment` (the same
   `source` string, truncated) were also already applied to every
   system-placed order in `mt5/executor.py`. **Part A's ask was therefore
   already implemented** — no new column, no new migration, no new
   comment/magic tagging was added. (Still unverified: whether the broker
   actually preserves the `comment`/`magic` fields on `positions_get()`/
   `orders_get()` — see "Not verified" below.)
2. **`sync_orders`/`sync_account` in `api/routes/accounts/_sync.py` already
   contained the full pending/filled/closed/cancelled reconciliation diff
   logic**, including the research-loop trigger — but were reachable *only*
   via their FastAPI routes (the dashboard's manual "Sync" button). Grepping
   the whole backend confirmed no other in-process caller existed. Neither
   function broadcast a WebSocket event on state change.

Given that, the actual implementation (branch `feature/pending-order-sync`)
was narrower than Part B originally described:

- **No new reconciliation loop was written.** `services/equity_poller.py`'s
  existing 60s per-account loop now calls the *existing* `sync_account()`
  (new helper `_reconcile_account_orders`) once per account per cycle,
  after the equity fetch — reusing, not duplicating, the diff/backfill/
  research-loop-trigger logic already in `_sync.py`. This opens a second,
  sequential (not concurrent) MT5 connection per account per cycle;
  `MT5Bridge`'s process-wide `_MT5_LOCK` still guarantees only one live
  MT5-thread-bound session at a time.
- **WebSocket broadcast was added**, not already present: a
  `_broadcast_positions_update()` helper in `_sync.py` now fires
  `positions_update` (reusing `services/mt5_poller.py`'s normalized position
  shape) whenever either function actually mutates a trade row or backfills
  a closed deal.
- **Verified rather than assumed** (per plan's own acceptance criteria):
  `check_position_limit`/`check_hedging` in `services/risk_manager.py`
  operate on the *live* MT5 positions list passed in by the caller, not the
  `trades` DB table — so manually-opened exposure was already correctly
  counted regardless of any DB row existing. `check_rate_limit` *does* query
  `trades` (symbol + `opened_at`, no `source` filter), so a manually
  backfilled trade (`source="manual"`) does count toward that symbol's
  AI rate limit — a pre-existing behavior, left as-is. Both are covered by
  tests in `backend/tests/test_order_reconciliation.py`.

**Not verified (needs a human + Windows/MT5 + demo account):**
- Whether the broker preserves the `comment`/`magic` fields on
  `positions_get()`/`orders_get()` results (Part A, item 3) — MT5 isn't
  installed in the Linux dev/CI sandbox that implemented this, so this could
  only be checked with a real terminal.
- End-to-end acceptance criteria 1 and 2 above (manual trade appears within
  one poll cycle; AI limit order fill updates within one poll cycle) —
  logic is unit-tested with a mocked bridge, but needs a live demo-account
  run to confirm timing/behavior against a real broker.
