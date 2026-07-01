# AI Pipeline Upgrade — Overview

Seven workstreams, each with its own branch/PR and plan doc. Numbered
roughly in dependency/priority order, but 01 and 02 are safety/visibility
fixes that should land regardless of what else slips.

| # | Plan | Branch | Depends on |
|---|------|--------|------------|
| 01 | [Pending-order sync + manual/AI trade tagging](01-pending-order-sync-and-trade-tagging.md) | `feature/pending-order-sync` | — |
| 02 | [News: enable by default + calendar page](02-news-enable-and-calendar-page.md) | `feature/news-enable` | — |
| 03 | [Enable 4-agent pipeline (Mode B) by default](03-enable-agent-pipeline-default.md) | `feature/agent-pipeline-default` | — |
| 04 | [Research loop trust-score + confidence gate](04-research-trust-score-and-confidence-gate.md) | `feature/research-trust-score` | — |
| 05 | [Ensemble/quorum voting across sub-agents](05-ensemble-quorum-voting.md) | `feature/ensemble-quorum` | 03 |
| 06 | [LLM cost + P&L attribution reporting](06-cost-pnl-tracking.md) | `feature/cost-pnl-tracking` | 01 |
| 07 | [Frontend/backend UX + edge-case audit](07-frontend-ux-edge-case-audit.md) | `feature/ux-edge-case-audit` | 01 |

## Why this order

- **01 first**: right now MT5 pending/filled orders are not reconciled
  against the `trades` table at all, and there's no way to tell an
  AI-placed trade from a manual one. The user is about to start manual
  trading on the same account this system trades — this is a correctness
  gap with real money, not a nice-to-have.
- **02**: `news_enabled` defaults to `false`; the user believed news
  analysis was running and silently getting zero events, when actually the
  gate was off. Cheap fix, high trust impact.
- **03** before **05**: ensemble/quorum voting across indicator/pattern/
  trend agents only makes sense once those agents are actually running by
  default (today they're opt-in via `enable_agent_pipeline`, off by
  default).
- **04** can proceed independently of 03/05 — it upgrades the research
  loop's output and the confidence gate, neither of which requires the
  4-agent mode.
- **06** depends on 01 because cost/P&L attribution needs to know which
  trades are AI-originated (source tagging) to avoid folding manual trades
  into "AI net profitability after LLM cost."
- **07** last — a UX/edge-case audit is most useful once manual-vs-AI
  trade visibility (01) and the rest of the pipeline changes exist to
  audit.

## Shared rules across all plans

- **One branch/PR per plan.** Do not combine plans in one PR.
- **Done-gate before merge:**
  - Backend: `uv run ruff check .` and `uv run pytest -v` both pass.
  - Frontend: `npm run lint` and `npm run build` both pass.
- **Behavior changes are expected** in these plans (unlike the earlier
  refactor-plans series) — this is feature work, not a pure refactor. Each
  plan doc calls out exactly what behavior changes and why.
- Any plan that touches order placement, risk checks, or the confidence
  gate must be tested against a **demo/paper MT5 account first** — never
  merge a change to the trading decision path straight to a live-money
  account without at least one manual dry run.
- Plan docs are scoped to stay well under ~32k tokens each; if a plan
  grows during execution, split it further rather than letting one doc
  balloon (e.g. `05` could become `05a-vote-schema.md`,
  `05b-decision-node-wiring.md`).

## Facts gathered before writing these plans (verified this session)

- **Pending order gap**: `services/position_maintenance/_service.py:175`
  queries `Trade.order_status.in_(["filled", "pending"])` but nothing
  reconciles against live MT5 state — no auto-cancel of stale pendings, no
  auto-close-sync. `equity_poller.py` already opens an MT5 connection per
  account every 60s and is the natural place to add this rather than a new
  poller.
- **News**: `core/config.py` — `news_enabled: bool = False`. Overridden at
  runtime by a `GlobalSettings` DB row (id=1) via
  `api/routes/settings/_global.py` (`GET` prefers DB row over `.env`
  fallback; `PATCH` writes DB + in-memory `settings.news_enabled`
  simultaneously — no restart needed). Scheduler jobs
  (`services/scheduler/_lifecycle.py:83,105,112`) are skipped entirely
  when the flag is off — this, not a fetch bug, explains "always no
  events." No `/news` page or news component exists anywhere in
  `frontend/app/` today.
- **Mode A vs Mode B**: default pipeline is the 3-role sequential mode
  (`market_analysis → execution_decision`). The 4-agent parallel mode
  (`indicator_agent ‖ pattern_agent ‖ trend_agent` → `decision_node`) exists
  and works via LangGraph `StateGraph` in `ai/agent_pipeline.py`, gated by
  `enable_agent_pipeline` (default off) with individual sub-agent toggles.
- **Research loop → LLM**: `services/research_loop.py` fires automatically
  every 30 closed trades (`RESEARCH_EVERY = 30`, triggered from
  `api/routes/accounts/_sync.py:204,218` on trade-close detection, not a
  cron job). It writes `backend/data/research_config.json`. Free-text
  `lessons`/`lesson_history` **are already injected** into every LLM call
  via `services/rag_context.py:299-315` (SQL-based context, confirmed no
  vector/embedding store exists anywhere). But `blocked_symbols` and
  `suggested_params` are written and **never read by the trading
  pipeline** — dead data today.
- **Risk checks**: `check_position_limit` and `check_rate_limit` already
  run *before* the LLM call (`services/ai_trading/_signal.py:313-345`) and
  short-circuit to a hardcoded HOLD without spending an LLM call if
  blocked. Hedging check necessarily runs after the LLM produces a
  direction — this is correct, not a gap.
- **Market-open check**: already exists
  (`services/ai_trading/_market_data.py:82-98`), runs before OHLCV
  fetch/LLM, raises `HTTPException(503)` if the market is closed.
- **Confidence gate**: currently a flat static threshold, not modulated by
  per-symbol research reliability.
