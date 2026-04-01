# Multi-Agent Analysis Pipeline

**Created:** 2026-03-31  
**Status:** Planning  
**Scope:** Extend the existing 3-role LLM pipeline into a parallel 4-agent pipeline using LangGraph

---

## Overview

Replace the sequential `market_analysis → chart_vision → execution_decision` pipeline with a LangGraph StateGraph that runs three specialist agents in parallel after an initial market context step, then feeds all results into a weighted decision agent.

The new pipeline is opt-in via `enable_agent_pipeline: bool` in config. When disabled, the existing orchestrator path is unchanged.

---

## Architecture

```
Input: symbol, timeframe, current_price, ohlcv, indicators, chart_image_b64
         │
         ▼
  ┌──────────────────┐
  │  market_analysis │  (sequential — same as today)
  │  (context node)  │
  └────────┬─────────┘
           │ market_context dict
           │
     ┌─────┴──────────────────────────────┐
     │             PARALLEL               │
     ▼             ▼                      ▼
┌──────────┐  ┌─────────────┐  ┌──────────────┐
│indicator │  │pattern_agent│  │ trend_agent  │
│  _agent  │  │  (vision)   │  │  (vision)    │
└────┬─────┘  └──────┬──────┘  └──────┬───────┘
     │               │                │
     └───────────────┴────────────────┘
                     │
                     ▼
            ┌────────────────┐
            │ decision_agent │
            │  (weighted)    │
            └────────┬───────┘
                     │
                     ▼
              TradingSignal dict
```

**LLM assignments:**

| Agent | LLM param | Recommended model |
|-------|-----------|-------------------|
| market_analysis | `market_analysis_llm` | default provider |
| indicator_agent | `indicator_agent_llm` | cheap (gemini-flash, gpt-4o-mini) |
| pattern_agent | `chart_vision_llm` | vision-capable |
| trend_agent | `chart_vision_llm` | vision-capable (same instance) |
| decision_agent | `execution_decision_llm` | default provider |

---

## Step 1 — Config additions

**File:** `backend/core/config.py`

Add 5 fields to the `Settings` model:

```python
# Multi-agent pipeline
enable_agent_pipeline: bool = False        # master toggle
enable_indicator_agent: bool = True
enable_pattern_agent: bool = True
enable_trend_agent: bool = True
indicator_agent_model: str = ""            # empty = provider default cheap model
```

`enable_agent_pipeline = False` keeps existing behavior with zero risk to current users.

**Checkboxes:**
- [ ] Add 5 fields to `Settings` in `config.py`
- [ ] Verify `uv run python -c "from core.config import settings; print(settings.enable_agent_pipeline)"` prints `False`

---

## Step 2 — Technical indicators service

**File:** `backend/services/technical_indicators.py`

### 2a. Indicator computation

Wrap pandas-ta to compute a fixed set of indicators from an OHLCV list. Returns a flat dict ready to pass to `indicator_agent`.

Interface:

```python
def compute_indicators(ohlcv: list[dict]) -> dict:
    """
    Input: list of {"time", "open", "high", "low", "close", "volume"}
    Output: {
        "rsi": float,
        "macd_line": float, "macd_signal": float, "macd_histogram": float,
        "stoch_k": float, "stoch_d": float,
        "roc": float,
        "willr": float,
    }
    Raises ValueError if fewer than 50 candles provided.
    """
```

Use pandas-ta defaults: RSI(14), MACD(12,26,9), Stoch(14,3,3), ROC(10), WILLR(14). Return only the last row values.

### 2b. Trendline fitting

Port `fit_trendlines_high_low` from QuantAgent `graph_util.py`. Uses iterative slope optimization with numpy.

Interface:

```python
def fit_trendlines(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    lookback: int = 50,
) -> tuple[float, float, float, float]:
    """
    Returns (support_slope, support_intercept, resist_slope, resist_intercept).
    Lines are defined as: price = slope * x + intercept  (x = bar index)
    """
```

### 2c. Trendline chart rendering

```python
def render_trendline_chart(
    ohlcv: list[dict],
    support_slope: float,
    support_intercept: float,
    resist_slope: float,
    resist_intercept: float,
) -> str:
    """Returns base64-encoded PNG. Uses matplotlib + mplfinance."""
    # Blue line = support, Red line = resistance
    # Overlaid on candlestick chart of last `lookback` candles
```

**Checkboxes:**
- [ ] `compute_indicators()` implemented with pandas-ta
- [ ] `fit_trendlines()` ported from QuantAgent
- [ ] `render_trendline_chart()` implemented with mplfinance
- [ ] Unit tests in `backend/tests/test_technical_indicators.py` (at least 3 cases)

---

## Step 3 — Individual agent modules

**Directory:** `backend/ai/agents/`

Each agent is a standalone async function. No classes needed.

### 3a. `indicator_agent.py`

```python
async def run_indicator_agent(
    indicators: dict,
    market_context: dict,
    llm,                   # LangChain BaseChatModel
) -> dict:
    """
    Returns:
    {
        "rsi": {"value": float, "signal": "overbought|oversold|neutral", "trend": str},
        "macd": {"crossover": "bullish|bearish|none", "histogram_trend": str, "signal": str},
        "stoch": {"k": float, "d": float, "signal": str},
        "roc": {"value": float, "signal": str},
        "willr": {"value": float, "signal": str},
        "overall": "bullish|bearish|neutral",
        "confidence": "low|medium|high",
    }
    """
```

Prompt strategy: provide indicator values as a structured block, ask LLM to interpret each and give overall reading. No tool calls. JSON output enforced via `with_structured_output` or regex fallback.

### 3b. `pattern_agent.py`

```python
async def run_pattern_agent(
    chart_image_b64: str,
    market_context: dict,
    llm,                   # vision-capable LangChain model
) -> dict:
    """
    Returns:
    {
        "pattern": str,                          # e.g. "head_and_shoulders" or "none"
        "completion_state": "forming|complete|breakout_confirmed",
        "confidence": "low|medium|high",
        "bias": "bullish|bearish|neutral",
    }
    """
```

Prompt includes the 16-pattern reference list (head & shoulders, double top/bottom, triangle types, wedge, flag, pennant, cup & handle, etc.). Image passed as base64 multipart message.

### 3c. `trend_agent.py`

```python
async def run_trend_agent(
    trendline_chart_b64: str,   # chart with blue/red lines drawn
    market_context: dict,
    llm,                        # vision-capable LangChain model
) -> dict:
    """
    Returns:
    {
        "trendline_structure": "ascending_channel|descending_channel|triangle|horizontal|other",
        "price_position": "above_support|at_resistance|between_levels|below_support",
        "trend_prediction": "upward|downward|sideways",
        "key_levels": {"support": float, "resistance": float},
        "confidence": "low|medium|high",
    }
    """
```

Prompt tells the agent: blue line = support, red line = resistance. Ask for structure interpretation and price position.

### 3d. `decision_agent.py`

```python
async def run_decision_agent(
    indicator_report: dict,
    pattern_report: dict,
    trend_report: dict,
    market_context: dict,
    llm,
) -> dict:
    """
    Returns:
    {
        "forecast_horizon": str,               # e.g. "4-8 hours"
        "signal": "LONG|SHORT|HOLD",
        "confidence": float,                   # 0.0 - 1.0
        "justification": str,
        "risk_reward_ratio": float,            # target 1.2 - 1.8
        "suggested_entry": float,
        "invalidation_condition": str,
    }
    """
```

Uses weighted 3-tier prompt from QuantAgent (momentum indicators weighted highest > chart patterns > trendlines). Prompt explicitly states weighting rationale.

**Checkboxes:**
- [ ] `backend/ai/agents/__init__.py` created (empty)
- [ ] `indicator_agent.py` with `run_indicator_agent()`
- [ ] `pattern_agent.py` with `run_pattern_agent()`
- [ ] `trend_agent.py` with `run_trend_agent()`
- [ ] `decision_agent.py` with `run_decision_agent()`
- [ ] All agents use `logger = logging.getLogger(__name__)` (no print)
- [ ] JSON parse fallback (regex) in each agent if `with_structured_output` fails

---

## Step 4 — LangGraph pipeline

**File:** `backend/ai/agent_pipeline.py`

### State schema

```python
class AgentPipelineState(TypedDict):
    # Inputs
    symbol: str
    timeframe: str
    current_price: float
    ohlcv: list[dict]
    indicators: dict                  # pre-computed by compute_indicators()
    chart_image_b64: str | None
    trendline_chart_b64: str | None   # pre-rendered by render_trendline_chart()
    # Context (filled by market_analysis node)
    market_context: dict | None
    # Agent outputs
    indicator_report: dict | None
    pattern_report: dict | None
    trend_report: dict | None
    # Final
    final_signal: dict | None
    error: str | None
```

### Graph structure

```python
def build_pipeline(
    market_analysis_llm,
    indicator_agent_llm,
    chart_vision_llm,
    execution_decision_llm,
    settings: Settings,
) -> CompiledGraph:
    graph = StateGraph(AgentPipelineState)

    graph.add_node("market_analysis", market_analysis_node)
    graph.add_node("parallel_agents", parallel_agents_node)   # runs 3 agents via asyncio.gather
    graph.add_node("decision", decision_node)

    graph.set_entry_point("market_analysis")
    graph.add_edge("market_analysis", "parallel_agents")
    graph.add_edge("parallel_agents", "decision")
    graph.add_edge("decision", END)

    return graph.compile()
```

The `parallel_agents_node` uses `asyncio.gather` to run indicator, pattern, and trend agents concurrently. Agents disabled via config are skipped (their report stays `None`); decision agent receives `None` for those inputs and handles gracefully.

### Error handling

Each node catches exceptions, logs them with `logger.error(...)`, and stores error message in state. Pipeline continues to decision node with partial data rather than hard-failing.

**Checkboxes:**
- [ ] `AgentPipelineState` TypedDict defined
- [ ] `market_analysis_node` implemented
- [ ] `parallel_agents_node` with `asyncio.gather` for 3 agents
- [ ] `decision_node` implemented
- [ ] `build_pipeline()` factory function
- [ ] Error handling: node exceptions logged, partial state forwarded
- [ ] Config flags (`enable_indicator_agent`, etc.) respected in `parallel_agents_node`

---

## Step 5 — Orchestrator integration

**File:** `backend/ai/orchestrator.py`

Add a single new public function:

```python
async def run_agent_pipeline(
    symbol: str,
    timeframe: str,
    current_price: float,
    ohlcv: list[dict],
    chart_image_b64: str | None = None,
    news_context: str | None = None,
    open_positions: list[dict] | None = None,
    trade_history: list[dict] | None = None,
) -> dict:
    """
    Entry point for the 4-agent pipeline. Called when settings.enable_agent_pipeline=True.
    
    Internally:
    1. Computes indicators via technical_indicators.compute_indicators(ohlcv)
    2. Fits trendlines + renders trendline chart if chart_image_b64 provided
    3. Builds LangGraph pipeline via agent_pipeline.build_pipeline(...)
    4. Invokes pipeline and returns final_signal dict
    """
```

Modify the existing `analyze_market()` method (or equivalent entry point) to branch:

```python
if settings.enable_agent_pipeline:
    return await run_agent_pipeline(...)
else:
    # existing 3-role pipeline (unchanged)
    ...
```

**Checkboxes:**
- [ ] `run_agent_pipeline()` added to `orchestrator.py`
- [ ] Branch logic in existing entry point
- [ ] LLM instances constructed respecting `indicator_agent_model` setting
- [ ] Logging: pipeline start/end, each agent result summary (INFO level)

---

## Step 6 — Dependencies

**File:** `backend/pyproject.toml`

Add if not already present:

```toml
[project.optional-dependencies]
agents = [
    "langgraph>=0.2",
    "pandas-ta>=0.3",
    "mplfinance>=0.12",
    "matplotlib>=3.8",
    "numpy>=1.26",
]
```

Or add directly to `[project.dependencies]` if these should always be available.

**Checkboxes:**
- [ ] Audit existing deps — `langgraph`, `pandas-ta`, `mplfinance` may already be listed
- [ ] Add missing deps to `pyproject.toml`
- [ ] Run `uv sync` to verify resolution
- [ ] `uv run python -c "import langgraph, pandas_ta, mplfinance"` succeeds

---

## Step 7 — Tests

**Files:** `backend/tests/`

| Test file | What it covers |
|-----------|---------------|
| `test_technical_indicators.py` | `compute_indicators()`, `fit_trendlines()`, edge cases |
| `test_agent_pipeline.py` | Full pipeline with mocked LLMs, verify state transitions |
| `test_indicator_agent.py` | Prompt construction, JSON parse, fallback |
| `test_decision_agent.py` | Weighted prompt, output schema validation |

Use `unittest.mock.AsyncMock` for LLM calls. Assert that disabled agents (via config) produce `None` report and decision agent handles gracefully.

**Checkboxes:**
- [ ] `test_technical_indicators.py` — at least compute + trendline tests
- [ ] `test_agent_pipeline.py` — happy path + one agent failure case
- [ ] `uv run pytest backend/tests/test_agent_pipeline.py -v` passes

---

## File Map

```
backend/
├── core/
│   └── config.py                         MODIFY — 5 new settings
├── ai/
│   ├── orchestrator.py                   MODIFY — add run_agent_pipeline(), branch logic
│   ├── agent_pipeline.py                 CREATE — LangGraph StateGraph
│   └── agents/
│       ├── __init__.py                   CREATE — empty
│       ├── indicator_agent.py            CREATE
│       ├── pattern_agent.py              CREATE
│       ├── trend_agent.py                CREATE
│       └── decision_agent.py             CREATE
├── services/
│   └── technical_indicators.py           CREATE — pandas-ta + trendlines + chart render
└── tests/
    ├── test_technical_indicators.py      CREATE
    └── test_agent_pipeline.py            CREATE
```

---

## Questions and Open Decisions

1. **chart_image_b64 source** — Does the caller always supply a chart PNG, or does the pipeline need to generate it from OHLCV? If the latter, `render_trendline_chart()` should also handle the base candlestick chart (not just the trendline overlay). Clarify before implementing Step 6.

2. **indicator_agent_model resolution** — ~~Resolved~~: `indicator_agent_model = ""` means **skip indicator agent entirely** (same effect as `enable_indicator_agent = False`). No default fallback.

3. **LangGraph version** — ~~Resolved~~: `langgraph` is NOT in pyproject.toml. Add `langgraph>=0.2` to Step 6.

4. **trendline_chart as separate image** — trend_agent receives a chart with trendlines drawn. Should this be the same resolution/timeframe as the original `chart_image_b64`, or a separate shorter-lookback window (e.g., last 50 bars only for trendline fitting)?

5. **Decision agent weighting** — The QuantAgent prompt uses momentum > pattern > trendlines. Is this weighting configurable, or hardcoded in the prompt? If configurable, add `agent_weights: dict` to settings.

6. **Backtest integration** — Should `run_agent_pipeline()` also be callable from the backtest engine (`BacktestEngine`)? If yes, the pipeline must accept pre-computed chart images per bar, which has performance implications.

7. **Partial results policy** — If one parallel agent fails (e.g., vision LLM timeout), should the decision agent proceed with 2/3 inputs, or should the whole pipeline return `HOLD`? Current plan: proceed with partial data, but this needs explicit confirmation.
