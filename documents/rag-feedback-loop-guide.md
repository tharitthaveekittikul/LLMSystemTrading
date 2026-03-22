# RAG Feedback Loop Guide for LLM Trading Systems
> Adapted from Polymarket AI Bot architecture for MT5/LangChain-based trading systems.
> Source: `documents/articles/logic_bot_article_fb.txt`

---

## Why This Matters

The Polymarket bot's key insight: **your LLM is flying blind if it doesn't know how it has performed before.**

Most systems (including ours currently) call the LLM with market data → get a signal → execute.
The bot adds a critical step: the LLM also receives **its own historical performance as context** (RAG) before deciding. This creates a self-aware system that knows:
- When it's been overconfident and shouldn't be trusted
- Which signals it should weight more
- What time of day it performs worst
- What lessons it learned from recent losses

**Your system already has the pipeline tracking infrastructure.** The gap is that this data isn't being fed back into the LLM prompt at decision time.

---

## What to Adopt (Priority Order)

### Priority 1 — RAG Context System (Highest Impact)

Before each LLM call in `ai/orchestrator.py`, build a `~4,000 char` context block injected into the prompt. Include:

| Section | Content | Benefit |
|---------|---------|---------|
| Overall Performance | WR%, total P&L, avg win/loss per symbol | LLM knows if strategy is working |
| Last 20 Trades | Signal values at entry, WIN/LOSS, P&L | LLM sees recent patterns |
| Signal Reliability | Which indicator signals led to wins vs losses | LLM weights signals correctly |
| Symbol Performance | WR by symbol (EURUSD vs XAUUSD etc.) | LLM avoids weak symbols |
| Timeframe Performance | WR by M15/H1/H4/D1 | LLM avoids weak TFs |
| Confidence Calibration | High-confidence trades' actual WR | Detects overconfidence |
| Time-of-Day Patterns | WR by session (London/NY/Asia) | LLM avoids bad sessions |
| Lessons from Recent Losses | Free-text lessons from post-trade analysis | Prevents repeat mistakes |

**Implementation in your codebase:**
- New service: `backend/services/rag_context.py`
- Called from `ai/orchestrator.py` inside `_call_llm_for_role()` before building the prompt
- Queries `trades`, `llm_calls`, `pipeline_runs` tables (already exist)
- Result appended to the system prompt

---

### Priority 2 — Post-Trade AI Analysis

When a trade closes, run a lightweight LLM call to analyze the outcome:

```
Input: trade entry data (signals used, LLM confidence, direction, symbol, TF)
       + trade outcome (WIN/LOSS, P&L, duration)

Output JSON:
{
  "correct_signals": ["rsi_oversold", "ema_cross"],
  "wrong_signals": ["bollinger_squeeze"],
  "key_factor": "strong NY session momentum aligned with H4 trend",
  "lesson": "Bollinger squeeze on M15 was noise during high-volatility NY open",
  "confidence_justified": false
}
```

**Store this in a new `trade_analysis` column (JSON) on the `trades` table.**
This feeds directly into Priority 1 (Lessons section) and Priority 3 (signal reliability).

**Where to add:**
- `backend/services/ai_trading.py` — trigger analysis when `closed_at` is set
- Or a new `backend/services/trade_analyzer.py` called from the sync/close flow

---

### Priority 3 — Confidence Calibration Tracking

Add a simple tracking layer: stated LLM confidence vs actual outcome.

```sql
-- Add to trades table (or a separate table)
llm_confidence       FLOAT    -- what LLM said (0.0 - 1.0)
confidence_bucket    VARCHAR  -- "very_high" / "high" / "medium" / "low"
confidence_justified BOOL     -- from post-trade analysis
```

**Why:** The Polymarket bot found high-confidence trades (≥60%) had a *lower* WR (43%) than low-confidence trades (58%). This is common. Your LLM needs to know this about itself to stop overtrading on false certainty.

RAG context section example:
```
Confidence Calibration (last 50 trades):
- Very High (≥80%): 38% WR ← overconfident!
- High (65-80%): 51% WR
- Medium (50-65%): 55% WR ← most reliable
```

---

### Priority 4 — Research Loop (Auto-Adjustment Every N Trades)

Every N closed trades (suggest N=30 for MT5 since trades are slower than prediction markets):

1. **Lesson injection** — regenerate lessons prompt section from latest data
2. **Signal reliability update** — recalculate which indicators are performing
3. **Parameter review** — LLM reviews stats and suggests confidence_threshold adjustments
4. **Symbol blocking** — auto-flag symbols with WR < 40% over 20+ trades

**New file:** `backend/services/research_loop.py`
**Trigger:** called from `ai_trading.py` when `closed_trade_count % N == 0`
**Output:** `backend/data/research_config.json` — lessons, signal weights, blocked symbols

---

### Priority 5 — data_requests Field (Nice-to-Have)

Add a `data_requests` field to LLM output JSON:
```json
{
  "action": "buy",
  "confidence": 0.72,
  "reasoning": "...",
  "data_requests": "Need correlation with DXY on H4 before NY session opens"
}
```

Store in DB → periodically review what data the LLM is asking for → that tells you what to build next.

---

### Priority 6 — Ensemble Pre-Filter (Advanced, Long-Term)

Use a small local Ollama model (9B) as a cheap pre-filter before your expensive model:

```
Small Model (fast, cheap): "Is this worth analyzing at all?" → YES/NO
                               ↓ (only if YES)
Large Model + RAG:         "Direction? Size? Confidence?" → full analysis
```

**When both models agree → higher confidence → more conviction.**
**When they disagree → skip or reduce size.**

For your system this maps to: Ollama 9B → execution_decision role, main model → market_analysis.

---

## What Does NOT Apply

| Article Concept | Why Skip |
|-----------------|----------|
| Kelly Criterion (Polymarket) | Polymarket prices are probabilities. MT5 uses lot sizing with SL/TP. Kelly can adapt but your risk model already covers this. |
| Market type tracking (Up/Down 15min vs Price Level) | Your equivalent: symbol × timeframe combinations |
| Circuit breaker ($20/day) | You already have kill switch — just tune the daily loss threshold |
| GradientBoosting ML classifier | Premature. Build 200+ trades first, then the feature importances will be meaningful. |
| LoRA fine-tuning | Way too early. Good idea long-term once you have 1000+ labeled trades. |

---

## Implementation Roadmap

```
Phase 1 — Foundation (implement first)
├── Add llm_confidence + confidence_bucket to trades table (Alembic migration)
├── Build backend/services/rag_context.py (query existing tables)
├── Inject RAG context into orchestrator.py market_analysis role
└── Test: does the LLM prompt now include performance history?

Phase 2 — Post-Trade Analysis
├── Add trade_analysis JSON column to trades table
├── Build backend/services/trade_analyzer.py
├── Trigger on trade close (after sync or manual close)
└── Verify lessons are being stored and readable

Phase 3 — Research Loop
├── Build backend/services/research_loop.py
├── Auto-trigger every 30 closed trades
├── Output research_config.json with lessons + signal reliability
└── RAG context reads from research_config.json for lessons section

Phase 4 — Dashboard
├── Add "Learning" tab to dashboard showing:
│   ├── Confidence calibration chart
│   ├── Signal reliability leaderboard
│   ├── Recent lessons
│   └── Research loop last-run date
```

---

## Key Files to Modify

| File | Change |
|------|--------|
| `backend/db/models.py` | Add `llm_confidence`, `confidence_bucket`, `trade_analysis` to Trade |
| `backend/alembic/versions/` | New migration for above columns |
| `backend/ai/orchestrator.py` | Inject RAG context into `market_analysis` prompt |
| `backend/services/ai_trading.py` | Trigger `trade_analyzer.analyze()` on trade close |
| **New** `backend/services/rag_context.py` | Build 10-section context from DB |
| **New** `backend/services/trade_analyzer.py` | LLM post-trade analysis |
| **New** `backend/services/research_loop.py` | Periodic auto-adjustment |

---

## Bottom Line

The most transformative single change: **feed the LLM its own win rate, confidence calibration, and lessons from recent losses before every decision.** This costs ~500 tokens per call but can materially change decision quality because the LLM will modulate its confidence based on its actual track record rather than being perpetually optimistic.

Your pipeline tracking infrastructure already captures everything needed — this is purely a query + prompt engineering problem.
