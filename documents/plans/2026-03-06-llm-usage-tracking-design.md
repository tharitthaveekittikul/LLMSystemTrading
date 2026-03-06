# LLM Usage Tracking & Dashboard — Design

**Date:** 2026-03-06
**Status:** Approved

## Overview

Two related features:

1. **Pipeline Logs Enhancement** — split the single `llm_analyzed` pipeline step into 3 separate LLM role steps, each recording token usage per call.
2. **LLM Usage Dashboard** — new `/llm-usage` page showing spend, token consumption, and cost breakdown by provider and model, with daily/hourly granularity toggle.

---

## Part 1: Pipeline Logs LLM Breakdown

### Problem

The current pipeline records one `llm_analyzed` step for all LLM work (market analysis, vision, execution decision combined into a single prompt). There is no way to see:
- Which LLM role consumed the most tokens or cost
- What model and provider handled each role
- Token breakdown (input vs output)

### Solution

Split into 3 distinct pipeline steps + track each in a new `llm_calls` table:

| Step Name              | Role                | Default Model          | Provider |
|------------------------|---------------------|------------------------|----------|
| `market_analysis_llm`  | Market analysis     | `gemini-2.5-flash`     | google   |
| `chart_vision_llm`     | Vision/chart read   | `gemini-2.5-flash-image` | google |
| `execution_decision_llm` | Trade decision    | `gemini-2.5-flash`     | google   |

Future model assignments (user-configurable):
- `execution_decision_llm` → `claude-sonnet-4-6`
- `market_analysis_llm` → `gpt-4o-mini`

### Orchestrator Refactor

`LLMAnalysisResult` dataclass extended to carry per-role token data:

```python
@dataclass
class LLMRoleResult:
    content: str | dict
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model: str
    provider: str
    duration_ms: int

@dataclass
class LLMAnalysisResult:
    signal: TradingSignal
    market_analysis: LLMRoleResult
    chart_vision: LLMRoleResult | None   # None if no chart image
    execution_decision: LLMRoleResult
```

Token extraction from LangChain response metadata:
- OpenAI: `response.response_metadata["token_usage"]`
- Anthropic: `response.response_metadata["usage"]`
- Google Gemini: `response.response_metadata["usage_metadata"]`

### Pipeline Step Changes

`ai_trading.py` records 3 steps instead of 1 `llm_analyzed`:

```
# Before: 1 step
tracer.record("llm_analyzed", ...)

# After: 3 steps
tracer.record("market_analysis_llm", ..., llm_call_id=...)
tracer.record("chart_vision_llm", ..., llm_call_id=...)      # skipped if no image
tracer.record("execution_decision_llm", ..., llm_call_id=...)
```

### Frontend Display Changes

Each LLM pipeline step card shows additional token badge row:

```
[✓] market_analysis_llm    gemini-2.5-flash  Google    234 ms
    ┌──────────────────────────────────────────────────────┐
    │ ↑ 1,240 input   ↓ 312 output   ∑ 1,552 total        │
    │ est. $0.000140                                        │
    └──────────────────────────────────────────────────────┘
```

---

## Part 2: LLM Usage Dashboard

### URL

`/llm-usage` — added to sidebar between Pipeline Logs and Analytics.

### Data Architecture

**New `llm_calls` table:**

```sql
CREATE TABLE llm_calls (
    id                SERIAL PRIMARY KEY,
    pipeline_step_id  INTEGER REFERENCES pipeline_steps(id) ON DELETE SET NULL,
    account_id        INTEGER REFERENCES accounts(id),
    provider          VARCHAR(50)  NOT NULL,  -- 'google' | 'anthropic' | 'openai'
    model             VARCHAR(100) NOT NULL,
    role              VARCHAR(50)  NOT NULL,  -- 'market_analysis' | 'chart_vision' | 'execution_decision'
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    total_tokens      INTEGER,
    cost_usd          NUMERIC(10, 8),         -- computed at insert time
    duration_ms       INTEGER,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_llm_calls_created_at ON llm_calls(created_at DESC);
CREATE INDEX idx_llm_calls_provider   ON llm_calls(provider);
CREATE INDEX idx_llm_calls_model      ON llm_calls(model);
```

**Pricing config** (`backend/core/llm_pricing.py`):

```python
# Last verified: 2026-03-06. Update when provider pricing changes.
LLM_PRICING: dict[str, dict[str, float]] = {
    # Google Gemini
    "gemini-2.5-flash":        {"input": 0.075,  "output": 0.30},
    "gemini-2.5-flash-image":  {"input": 0.075,  "output": 0.30},
    "gemini-1.5-pro":          {"input": 1.25,   "output": 5.00},
    # Anthropic Claude
    "claude-sonnet-4-6":       {"input": 3.00,   "output": 15.00},
    "claude-opus-4-6":         {"input": 15.00,  "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    # OpenAI
    "gpt-4o":                  {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":             {"input": 0.15,   "output": 0.60},
}

def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = LLM_PRICING.get(model)
    if not pricing:
        return None
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
```

### API Endpoints

All under `/api/v1/llm-usage/`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/summary` | Summary card data (period: `day`, `week`, `month`) |
| GET | `/timeseries` | Chart data (granularity: `hourly`, `daily`; days: int) |
| GET | `/by-model` | Per-model breakdown |
| GET | `/pricing` | Pricing reference table |

**Summary response:**
```json
{
  "total_cost_usd": 0.0234,
  "total_tokens": 312450,
  "total_calls": 89,
  "active_models": ["gemini-2.5-flash", "gemini-2.5-flash-image"],
  "by_provider": {
    "google":    {"cost_usd": 0.0234, "tokens": 312450, "calls": 89},
    "anthropic": {"cost_usd": 0,      "tokens": 0,      "calls": 0},
    "openai":    {"cost_usd": 0,      "tokens": 0,      "calls": 0}
  }
}
```

**Timeseries response (daily):**
```json
[
  {"date": "2026-03-01", "google": 0.0012, "anthropic": 0, "openai": 0},
  {"date": "2026-03-02", "google": 0.0018, "anthropic": 0, "openai": 0}
]
```

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│ LLM Usage                     [Period: This Month ▾]        │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ Total Spend  │ Total Tokens │ Total Calls  │ Active Models  │
│  $0.024 USD  │  312,450     │  89 calls    │  2 models      │
├──────────────┴──────────────┴──────────────┴────────────────┤
│ [All] [Google Gemini] [Anthropic] [OpenAI]                  │
├─────────────────────────────────────────────────────────────┤
│ Spend Over Time                 ● Spend  ○ Tokens           │
│ (stacked bar chart, providers colored)  [Daily | Hourly]    │
├───────────────────────────────┬─────────────────────────────┤
│ Model Breakdown               │ Provider Share (donut)      │
│ Model       Calls Tokens Cost │  ████ Google  100%          │
│ gemini-2.5… 60    210K  $0.016│  ░░░░ Anthropic 0%          │
│ gemini-img  29     42K  $0.003│  ░░░░ OpenAI 0%             │
│ claude-son. 0       0   —     │                             │
│ gpt-4o-mini 0       0   —     │                             │
├───────────────────────────────┴─────────────────────────────┤
│ Model Pricing Reference                                     │
│  gemini-2.5-flash       Input $0.075/1M · Output $0.30/1M  │
│  gemini-2.5-flash-image Input $0.075/1M · Output $0.30/1M  │
│  claude-sonnet-4-6      Input $3.00/1M  · Output $15.00/1M │
│  gpt-4o-mini            Input $0.15/1M  · Output $0.60/1M  │
└─────────────────────────────────────────────────────────────┘
```

### Frontend Components

```
frontend/src/app/llm-usage/
└── page.tsx                        Main page with layout

frontend/src/components/llm-usage/
├── llm-usage-summary-cards.tsx     4 summary metric cards
├── llm-usage-timeseries-chart.tsx  Stacked bar chart (recharts)
├── llm-usage-model-table.tsx       Per-model breakdown table
├── llm-provider-share-chart.tsx    Donut chart (recharts)
└── llm-pricing-reference.tsx       Static pricing cards
```

Frontend API client additions in `src/lib/api.ts`:
```typescript
llmUsageApi.getSummary(period)      → LLMUsageSummary
llmUsageApi.getTimeseries(params)   → LLMTimeseriesPoint[]
llmUsageApi.getByModel()            → LLMModelUsage[]
llmUsageApi.getPricing()            → LLMPricingEntry[]
```

### TypeScript Types (`src/types/trading.ts` additions)

```typescript
interface LLMUsageSummary {
  total_cost_usd: number
  total_tokens: number
  total_calls: number
  active_models: string[]
  by_provider: Record<string, { cost_usd: number; tokens: number; calls: number }>
}

interface LLMTimeseriesPoint {
  date: string
  google: number
  anthropic: number
  openai: number
}

interface LLMModelUsage {
  model: string
  provider: string
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
}
```

---

## Implementation Order

1. **Alembic migration** — add `llm_calls` table
2. **`core/llm_pricing.py`** — pricing table + `compute_cost()`
3. **`db/models.py`** — add `LLMCall` SQLAlchemy model
4. **`ai/orchestrator.py`** — refactor into 3 role methods + token extraction
5. **`services/pipeline_tracer.py`** — `record_llm_call()` helper
6. **`services/ai_trading.py`** — wire 3 steps, replace `llm_analyzed`
7. **`api/routes/llm_usage.py`** — 4 query endpoints
8. **`api/schemas/llm_usage.py`** — Pydantic response models
9. **`main.py`** — register llm_usage router
10. **Frontend types** — add to `trading.ts`
11. **Frontend API client** — `llmUsageApi` in `api.ts`
12. **Frontend components** — `llm-usage/` directory (5 components)
13. **Frontend page** — `/llm-usage/page.tsx`
14. **Sidebar** — add "LLM Usage" nav item
15. **Pipeline step card** — add token badge UI for LLM steps
