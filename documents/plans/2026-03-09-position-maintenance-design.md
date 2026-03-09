# Position Maintenance Task — Design Document

**Date**: 2026-03-09
**Status**: Approved
**Feature**: Scheduled AI-driven position maintenance (hold / close / modify)

---

## 1. Overview

A scheduled maintenance task runs at a configurable global interval and reviews all open positions and pending orders across all active accounts. For each eligible position it runs a 3-role LLM pipeline (technical analysis → sentiment analysis → decision), validates the decision against the underlying strategy's risk constraints, and executes the recommended MT5 action (hold, close, or modify SL/TP).

---

## 2. Design Decisions

| Question | Decision |
|----------|----------|
| Order scope | Open positions + pending limit/stop orders |
| Strategy-level switch | `maintenance_enabled: bool` on `strategies` table |
| Per-order switch | `maintenance_enabled: bool` on `trades` table |
| Sentiment source | Market news (ForexFactory, same as existing `news_enabled`) |
| LLM structure | 3 roles mirroring existing pipeline (technical / sentiment / decision) |
| Interval config | Global `maintenance_interval_minutes` in Settings (default 60) |
| Position fetch | Fresh MT5 call once per account per sweep (no Redis caching) |
| Architecture | New `PositionMaintenanceService` (Approach A — dedicated service) |

---

## 3. Architecture

```
APScheduler — IntervalTrigger(minutes=maintenance_interval_minutes)
    └─ PositionMaintenanceService.run_maintenance_sweep(db)
          ├─ for each active account
          │     ├─ kill switch check → skip account if active
          │     ├─ MT5Bridge.get_positions()        [1 MT5 call]
          │     ├─ MT5Bridge.get_pending_orders()   [1 MT5 call]
          │     └─ for each position/order:
          │           ├─ lookup Trade row → skip if maintenance_enabled=False
          │           ├─ lookup Strategy row → skip if maintenance_enabled=False
          │           └─ run_single_maintenance(position, strategy, account, db)
          │
          └─ [run_single_maintenance — PipelineTracer, task_type="maintenance"]
                Step 1: Fetch OHLCV (Redis cache by TF) + compute indicators
                Step 2: LLM role maintenance_technical_analysis
                Step 3: LLM role maintenance_sentiment_analysis
                Step 4: LLM role maintenance_decision → HOLD | CLOSE | MODIFY
                Step 5: ConstraintValidator
                Step 6: MT5 action
                Step 7: PipelineTracer.finalize() + WebSocket broadcast
```

---

## 4. Components

### New Files
- `backend/services/position_maintenance.py` — `PositionMaintenanceService`

### Modified Files
- `backend/ai/orchestrator.py` — add `async review_position(...)` (3-role maintenance pipeline)
- `backend/mt5/executor.py` — add `async modify_order(ticket, new_sl, new_tp)`
- `backend/services/scheduler.py` — register global maintenance job
- `backend/core/config.py` — add `maintenance_interval_minutes: int = 60`
- `backend/api/routes/settings.py` — expose new setting
- Frontend: settings page, strategies page, trades table, pipeline page filter

---

## 5. Database Changes (1 Alembic Migration)

| Table | Column | Type | Default | Notes |
|-------|--------|------|---------|-------|
| `strategies` | `maintenance_enabled` | `bool` | `True` | Disable maintenance for a strategy globally |
| `trades` | `maintenance_enabled` | `bool` | `True` | Disable maintenance for a specific position/order |
| `pipeline_runs` | `task_type` | `varchar(20)` | `"signal"` | Discriminator: `"signal"` or `"maintenance"` |

---

## 6. LLM Roles (3-Role Pipeline via orchestrator.review_position)

### Role 1: `maintenance_technical_analysis`
**Input:**
```json
{
  "symbol": "EURUSD",
  "timeframe": "H1",
  "ohlcv_last_20": [...],
  "indicators": { "sma20": 1.0850, "high_20": 1.0920, "low_20": 1.0800 },
  "position": {
    "direction": "BUY",
    "entry_price": 1.0830,
    "current_price": 1.0870,
    "current_sl": 1.0800,
    "current_tp": 1.0900,
    "unrealized_pnl": 40.0,
    "duration_hours": 6.5
  },
  "strategy_params": { "sl_pips": 30, "tp_pips": 60, "risk_pct": 1.0 }
}
```
**Output:** `{ "trend": "UPTREND", "key_support": 1.0820, "key_resistance": 1.0900, "position_evaluation": "...", "technical_score": 0.6 }`

### Role 2: `maintenance_sentiment_analysis`
**Input:** symbol, upcoming news events (next 24h), recent news (last 8h), trade history summary
**Output:** `{ "sentiment_direction": "BULLISH", "event_risk": "MEDIUM", "key_events": [...], "sentiment_score": 0.4 }`

### Role 3: `maintenance_decision`
**Input:** position state + technical output + sentiment output + strategy constraints
**Output:**
```json
{
  "action": "MODIFY",
  "new_sl": 1.0840,
  "new_tp": 1.0920,
  "rationale": "Position profitable, trailing SL to lock in 10 pips...",
  "confidence": 0.78
}
```
Actions: `HOLD | CLOSE | MODIFY`

---

## 7. Constraint Validator

Applied after the decision LLM call, before any MT5 action. If any check fails, action is downgraded to `HOLD` and the reason is recorded in `pipeline_steps`.

| Constraint | Rule | Applies To |
|-----------|------|-----------|
| Min SL distance | `abs(current_price - new_sl) >= strategy.sl_pips * pip_size` | MODIFY |
| Trailing stop logic | If in profit: `new_sl >= current_sl` (BUY) or `new_sl <= current_sl` (SELL) | MODIFY |
| Max risk per trade | `(balance * risk_pct) / sl_distance_lots >= volume` | MODIFY |
| Minimum R:R | `abs(new_tp - entry) >= abs(new_sl - entry)` (1:1) | MODIFY |

---

## 8. Pipeline Logging

All maintenance runs use `PipelineTracer` with `task_type="maintenance"`. Each run creates:
- 1 `pipeline_runs` row (`task_type="maintenance"`, `final_action=HOLD|CLOSE|MODIFY`)
- N `pipeline_steps` rows (one per step)
- 3 `llm_calls` rows (one per LLM role)

**Sweep-level log messages:**
```
INFO  scheduler: Maintenance sweep started: interval=60min, accounts=3
INFO  position_maintenance: Maintenance account=1 (Main): 4 positions eligible, 2 skipped
INFO  position_maintenance: EURUSD H1 ticket=12345 → MODIFY (SL: 1.0800→1.0840, TP unchanged)
INFO  position_maintenance: GBPUSD H4 ticket=12346 → HOLD (confidence 0.52 below threshold)
INFO  position_maintenance: Maintenance sweep complete: 1 MODIFY, 2 HOLD, 0 CLOSE, 2 SKIP, 0 ERR
```

**WebSocket event** per position (same pattern as `pipeline_run_complete`):
```json
{ "event": "maintenance_run_complete", "data": { "account_id": 1, "symbol": "EURUSD", "ticket": 12345, "action": "MODIFY", "run_id": 789 } }
```

---

## 9. Error Handling

| Failure | Behaviour |
|---------|----------|
| MT5 unavailable for account | Skip entire account, `WARNING` log, no positions processed |
| LLM call fails (any role) | HOLD, `pipeline_steps` status=`"failed"`, no MT5 action |
| Constraint rejected | HOLD, step `constraint_rejected` records which rule + LLM suggestion |
| MT5 modify/close fails | Log error, record in step, no retry |
| Single position exception | Isolated in `try/except`, sweep continues for other positions |

---

## 10. Frontend Changes

| Page | Change |
|------|--------|
| `/settings` | Add `maintenance_interval_minutes` number input + global `maintenance_task_enabled` toggle |
| `/strategies` | Add `Maintenance` toggle per strategy card |
| Trades/positions table | Add `Maintenance On/Off` toggle per row |
| `/pipeline` | Add `task_type` filter chip: `All | Signal | Maintenance` |

---

## 11. Execution Order (Implementation Sequence)

1. Alembic migration (3 columns: strategies.maintenance_enabled, trades.maintenance_enabled, pipeline_runs.task_type)
2. core/config.py — add `maintenance_interval_minutes`
3. mt5/executor.py — add `modify_order()`
4. ai/orchestrator.py — add `review_position()` (3-role pipeline + schemas)
5. services/position_maintenance.py — `PositionMaintenanceService`
6. services/scheduler.py — register maintenance job
7. api/routes/settings.py — expose new setting
8. Frontend: settings + strategies + trades + pipeline filter
9. Alembic seed: default TaskLLMAssignment rows for 3 new maintenance roles
