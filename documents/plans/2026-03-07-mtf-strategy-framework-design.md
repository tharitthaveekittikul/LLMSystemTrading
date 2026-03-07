# Multi-Timeframe Strategy Framework — Design Document

**Date**: 2026-03-07
**Status**: Approved
**Scope**: Multi-timeframe data layer, 5 strategy execution types, full harmonic pattern engine, strategy analytics showcase

---

## 1. Overview

This design adds three major subsystems to the existing trading system:

1. **MTF Data Layer** — replaces single-timeframe OHLCV fetching with a declared multi-timeframe contract
2. **Strategy Execution Framework** — 5 typed base classes covering every LLM/rule orchestration pattern
3. **Harmonic Pattern Engine** — full Williams Fractals pivot detection + 7 pattern implementations + PRZ calculation
4. **Strategy Analytics Showcase** — global analytics shell + per-strategy-type detail panels

All subsystems share the same `strategy.run(market_data)` interface. Backtest and live trading use identical code paths.

### Integration Points (unchanged)
- `BacktestEngine` — extended, not replaced
- `Scheduler` — updated to pass `MTFMarketData`
- `AI Orchestrator` — updated to receive MTF context
- Frontend backtest page — extended with analytics route

---

## 2. Multi-Timeframe Data Layer

### 2.1 Core Data Structures

**File**: `backend/services/mtf_data.py`

```python
@dataclass
class OHLCV:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int

@dataclass
class TimeframeData:
    tf: str
    candles: list[OHLCV]   # sorted oldest→newest; newest = most recently closed candle

@dataclass
class MTFMarketData:
    symbol: str
    primary_tf: str                        # timing clock (triggers on this TF close)
    current_price: float
    timeframes: dict[str, TimeframeData]   # {"H1": ..., "M15": ..., "M1": ...}
    indicators: dict[str, float]           # computed on primary_tf candles
    trigger_time: datetime                 # UTC time of primary candle close
```

### 2.2 Live Data Fetcher

```python
class MTFDataFetcher:
    async def fetch(
        self,
        symbol: str,
        primary_tf: str,
        context_tfs: list[str],
        candle_counts: dict[str, int],    # {"H1": 20, "M15": 10, "M1": 5}
    ) -> MTFMarketData
```

- Checks Redis cache per (symbol, tf); falls back to MT5 via `run_in_executor`
- Returns only **closed** candles (excludes the currently forming candle)
- Indicators computed on `primary_tf` candles after fetch

### 2.3 Backtest Data Loader

**File**: `backend/services/mtf_backtest_loader.py`

```python
class MTFBacktestLoader:
    def __init__(self, csv_paths: dict[str, str])   # {"M15": "path.csv", "H1": "path.csv", "M1": "path.csv"}

    def iter_primary_closes(
        self,
        primary_tf: str,
        context_tfs: list[str],
        candle_counts: dict[str, int],
        start_date: datetime,
        end_date: datetime,
    ) -> Iterator[MTFMarketData]
```

**Alignment rule (no data leak):**
At each primary TF candle close at time `T`:
- Primary TF candles: all with `close_time ≤ T`, last N
- Each context TF: all with `close_time ≤ T`, last N
- The currently forming candle on any TF is **never** included

### 2.4 CSV Format

MT5 export format (tab-separated):
```
<DATE>       <TIME>      <OPEN>   <HIGH>   <LOW>    <CLOSE>  <TICKVOL>  <VOL>  <SPREAD>
2017.01.02   00:00:00    143.878  143.943  143.851  143.878  61         ...    200
```
- Date parse format: `%Y.%m.%d %H:%M:%S`
- All times treated as UTC
- `<SPREAD>` column ignored (spread configured per backtest run)

---

## 3. Strategy Base Class Hierarchy

### 3.1 Class Tree

```
AbstractStrategy                          (backend/strategies/base.py)
├── LLMOnlyStrategy          llm_only
├── RuleThenLLMStrategy      rule_then_llm
├── RuleOnlyStrategy         rule_only
├── HybridValidatorStrategy  hybrid_validator
└── MultiAgentStrategy       multi_agent
```

### 3.2 AbstractStrategy (common interface)

```python
class AbstractStrategy(ABC):
    # Declared by author — engine reads these
    primary_tf: str = "M15"
    context_tfs: list[str] = ["H1", "M1"]
    candle_counts: dict[str, int] = {"H1": 20, "M15": 10, "M1": 5}
    symbols: list[str] = []
    execution_mode: str = ""          # set by each subclass

    # Engine calls this — each subclass owns orchestration
    @abstractmethod
    async def run(self, market_data: MTFMarketData) -> StrategyResult: ...

    # Frontend reads this to select the analytics detail panel
    @abstractmethod
    def analytics_schema(self) -> dict: ...
```

### 3.3 StrategyResult

```python
@dataclass
class StrategyResult:
    action: Literal["BUY", "SELL", "HOLD"]
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    confidence: float                  # 0.0–1.0
    rationale: str
    timeframe: str
    # Optional — populated by harmonic/pattern strategies
    pattern_name: str | None = None
    pattern_metadata: dict | None = None   # {xabcd_points, ratios, quality_score}
    # Populated by LLM types
    llm_result: LLMAnalysisResult | None = None
```

### 3.4 Per-Type Contracts

#### Type 1 — LLMOnlyStrategy
```python
class LLMOnlyStrategy(AbstractStrategy):
    execution_mode = "llm_only"

    @abstractmethod
    def system_prompt(self) -> str: ...

    def build_context(self, market_data: MTFMarketData) -> str:
        """Override to customize context sent to LLM. Default structures H1→M15→M1."""
        ...

    async def run(self, market_data: MTFMarketData) -> StrategyResult:
        # Builds MTF context string → calls orchestrator (all 3 roles) → returns result
```

Triggers: Every primary_tf candle close. Most expensive (LLM on every candle).

#### Type 2 — RuleThenLLMStrategy
```python
class RuleThenLLMStrategy(AbstractStrategy):
    execution_mode = "rule_then_llm"

    @abstractmethod
    def check_trigger(self, market_data: MTFMarketData) -> bool: ...

    @abstractmethod
    def system_prompt(self) -> str: ...

    async def run(self, market_data: MTFMarketData) -> StrategyResult:
        # check_trigger() → False = HOLD immediately (no LLM call)
        # check_trigger() → True  = call orchestrator → return signal
```

Cost saving: LLM called only when rule fires. Rule acts as a cheap pre-filter.

#### Type 3 — RuleOnlyStrategy
```python
class RuleOnlyStrategy(AbstractStrategy):
    execution_mode = "rule_only"

    @abstractmethod
    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None: ...

    async def run(self, market_data: MTFMarketData) -> StrategyResult:
        # check_rule() → None = HOLD
        # check_rule() → signal = return directly (zero LLM cost)
```

Zero LLM cost. Fully deterministic. Ideal for pattern strategies.

#### Type 4 — HybridValidatorStrategy
```python
class HybridValidatorStrategy(AbstractStrategy):
    execution_mode = "hybrid_validator"

    @abstractmethod
    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None: ...

    @abstractmethod
    def build_validation_context(
        self, signal: StrategyResult, trade: Trade, market_data: MTFMarketData
    ) -> str: ...

    async def run(self, market_data: MTFMarketData) -> StrategyResult:
        # Phase 1: check_rule() → if None, HOLD
        # Phase 2: execute order immediately on signal
        # Phase 3: send validation context to LLM → LLM decides HOLD or CLOSE_EARLY
        # Note: Phase 3 runs async after order placement
```

Rule executes first (no LLM latency on entry). LLM monitors after entry.

#### Type 5 — MultiAgentStrategy
```python
class MultiAgentStrategy(AbstractStrategy):
    execution_mode = "multi_agent"

    @abstractmethod
    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None: ...

    @abstractmethod
    def system_prompt(self) -> str: ...

    async def run(self, market_data: MTFMarketData) -> StrategyResult:
        # Run rule check + LLM analysis in parallel (asyncio.gather)
        # Consensus required: both must agree on BUY or both on SELL
        # Disagreement → HOLD
        # Agreement → return signal with higher of the two confidences
```

Most conservative. Highest signal quality, lowest frequency.

### 3.5 DB Schema Change

`strategies.strategy_type` → `strategies.execution_mode`

Old values `config | prompt | code` → migrated to new values:
- `config` → `llm_only`
- `prompt` → `llm_only`
- `code` → determined by class's `execution_mode` attribute at migration time

New valid values: `llm_only | rule_then_llm | rule_only | hybrid_validator | multi_agent`

**Alembic migration**: rename column + update CHECK constraint + backfill existing rows.

---

## 4. Harmonic Pattern Engine

### 4.1 Module Structure

```
backend/strategies/harmonic/
├── __init__.py
├── swing_detector.py        # Williams Fractals pivot detection
├── pattern_scanner.py       # orchestrates all 7 patterns against pivot list
├── prz_calculator.py        # PRZ zone + SL/TP from completed pattern
├── harmonic_strategy.py     # RuleOnlyStrategy concrete implementation
└── patterns/
    ├── base_pattern.py      # ratio validation with ±5% tolerance
    ├── abcd.py
    ├── gartley.py
    ├── bat.py
    ├── butterfly.py
    ├── crab.py
    ├── shark.py
    └── cypher.py
```

### 4.2 Williams Fractals Pivot Detection

**File**: `backend/strategies/harmonic/swing_detector.py`

```python
@dataclass
class Pivot:
    index: int
    time: datetime
    price: float
    type: Literal["high", "low"]
    confirmed: bool               # True once n candles have closed after it

def find_pivots(candles: list[OHLCV], n: int = 2) -> list[Pivot]:
    """
    Pivot High at i: candle[i].high > candle[i-n..i-1] AND candle[i].high > candle[i+1..i+n]
    Pivot Low  at i: candle[i].low  < candle[i-n..i-1] AND candle[i].low  < candle[i+1..i+n]

    Only returns confirmed pivots (i+n < len(candles)).
    Never repaints — pivot at i is confirmed only after candles i+1..i+n have closed.
    Default n=2 → requires 2 candles on each side (5-bar fractal, industry standard).
    """
```

Returns alternating high/low pivots (ZigZag-ordered). Consecutive same-type pivots
are collapsed to the most extreme value.

### 4.3 Pattern Ratio Table

Tolerance: **±5%** on all ratio checks (configurable per instance).

| Pattern   | AB/XA           | BC/AB           | CD/BC           | D point            |
|-----------|-----------------|-----------------|-----------------|---------------------|
| Gartley   | 0.618           | 0.382–0.886     | 1.272–1.618     | 0.786 retrace of XA |
| Bat       | 0.382–0.500     | 0.382–0.886     | 1.618–2.618     | 0.886 retrace of XA |
| Butterfly | 0.786           | 0.382–0.886     | 1.618–2.618     | 1.272–1.618 ext XA  |
| Crab      | 0.382–0.618     | 0.382–0.886     | 2.618–3.618     | 1.618 ext XA        |
| Shark     | 0.446–0.618 OX  | 1.130–1.618 XA  | —               | 0.886–1.130 retrace OX |
| Cypher    | 0.382–0.618     | 1.272–1.414 XA  | 0.786 retrace XC| —                  |
| ABCD      | —               | 0.618–0.786     | 1.272–1.618     | —                  |

- **Bullish** pattern: X high → A low → B high → C low → D low (entry BUY at D)
- **Bearish** pattern: X low → A high → B low → C high → D high (entry SELL at D)
- Shark uses 5-point OXABC notation; D = C in standard XABCD notation

### 4.4 Pattern Base Class

**File**: `backend/strategies/harmonic/patterns/base_pattern.py`

```python
@dataclass
class PatternResult:
    pattern_name: str
    direction: Literal["bullish", "bearish"]
    points: dict[str, Pivot]          # {"X": pivot, "A": pivot, "B": pivot, "C": pivot, "D": pivot}
    ratios: dict[str, float]          # actual computed ratios
    expected_ratios: dict[str, tuple] # (min, max) per ratio
    ratio_accuracy: float             # 0–1, how close ratios are to ideal
    quality_score: float              # ratio_accuracy × pattern_size_score × h1_trend_alignment
    prz_high: float
    prz_low: float

class BaseHarmonicPattern(ABC):
    name: str
    tolerance: float = 0.05

    def validate(self, x, a, b, c, d) -> PatternResult | None:
        """Check all ratios. Return PatternResult if valid, None if invalid."""

    def _ratio_in_range(self, actual: float, expected_min: float, expected_max: float) -> bool:
        lo = expected_min * (1 - self.tolerance)
        hi = expected_max * (1 + self.tolerance)
        return lo <= actual <= hi

    def _ratio_accuracy_score(self, actual: float, ideal: float) -> float:
        """1.0 = perfect, approaches 0 as deviation increases."""
        return max(0.0, 1.0 - abs(actual - ideal) / ideal)
```

### 4.5 Pattern Scanner

**File**: `backend/strategies/harmonic/pattern_scanner.py`

```python
ALL_PATTERNS = [Gartley(), Bat(), Butterfly(), Crab(), Shark(), Cypher(), ABCD()]

def scan(
    pivots: list[Pivot],
    min_pattern_size_pips: float = 20.0,
    h1_candles: list[OHLCV] | None = None,    # for trend alignment scoring
) -> list[PatternResult]:
    """
    Slide a window over the last N pivots, test all 7 patterns.
    Returns all valid patterns sorted by quality_score descending.
    Only scans the most recent pivots to keep latency low (last 20 pivots max).
    """
```

Quality score components:
- `ratio_accuracy`: how precisely ratios match ideal values (0–1)
- `pattern_size_score`: normalized pattern pip size — larger = more significant (0–1)
- `h1_trend_alignment`: +0.2 bonus if D direction aligns with H1 trend (optional, requires H1 candles)

### 4.6 PRZ Calculator

**File**: `backend/strategies/harmonic/prz_calculator.py`

```python
def to_signal(
    pattern: PatternResult,
    market_data: MTFMarketData,
    atr_multiplier_sl: float = 0.5,
) -> StrategyResult:
    """
    Entry:      D.price (trigger on M15 candle close confirming D pivot)
    PRZ zone:   pattern.prz_low → pattern.prz_high
    Stop loss:  beyond X point ± atr(14) × atr_multiplier_sl
    TP1:        0.382 retracement of CD leg
    TP2:        0.618 retracement of CD leg
    Confidence: pattern.quality_score
    """
```

ATR(14) computed from M15 candles at time of signal.

Stop loss placement:
- Bullish: `X.price - (atr × multiplier)` (below X low)
- Bearish: `X.price + (atr × multiplier)` (above X high)

### 4.7 HarmonicStrategy

**File**: `backend/strategies/harmonic/harmonic_strategy.py`

```python
class HarmonicStrategy(RuleOnlyStrategy):
    primary_tf = "M15"
    context_tfs = ["H1", "M1"]
    candle_counts = {"H1": 20, "M15": 50, "M1": 5}
    symbols = ["XAUUSD", "GBPJPY", "EURUSD", "GBPUSD"]   # override per instance

    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None:
        m15_candles = market_data.timeframes["M15"].candles
        h1_candles = market_data.timeframes["H1"].candles

        pivots = swing_detector.find_pivots(m15_candles, n=2)
        if len(pivots) < 5:
            return None

        patterns = pattern_scanner.scan(pivots, h1_candles=h1_candles)
        if not patterns:
            return None

        best = patterns[0]   # highest quality_score
        return prz_calculator.to_signal(best, market_data)

    def analytics_schema(self) -> dict:
        return {
            "panel_type": "pattern_grid",
            "group_by": "pattern_name",
            "heatmap_axes": ["symbol", "pattern_name"],
            "metrics": ["trades", "win_rate", "profit_factor", "total_pnl", "avg_win", "avg_loss"],
        }
```

---

## 5. Backtest Engine Updates

### 5.1 BacktestConfig

```python
@dataclass
class BacktestConfig:
    strategy: AbstractStrategy
    symbol: str
    csv_paths: dict[str, str]         # {"M15": "...", "H1": "...", "M1": "..."}
    start_date: datetime
    end_date: datetime
    initial_balance: float = 10_000.0
    spread_pips: float = 1.0
    execution_mode: Literal["close_price", "intra_candle"] = "close_price"
    max_llm_calls: int = 500          # ignored for rule_only strategies
```

`csv_paths` must include `strategy.primary_tf` and all `strategy.context_tfs`.

### 5.2 Engine Changes

- `BacktestEngine.__init__` accepts `BacktestConfig` (replaces old signature)
- Internally creates `MTFBacktestLoader(config.csv_paths)`
- Main loop iterates `loader.iter_primary_closes(...)` → yields `MTFMarketData`
- Calls `await strategy.run(market_data)` → receives `StrategyResult`
- Stores `result.pattern_name` + `result.pattern_metadata` on `BacktestTrade`

### 5.3 DB Schema Additions

**`backtest_trades` table:**
```sql
pattern_name     VARCHAR(50)   NULLABLE   -- "Gartley", "Bat", "Cypher", etc.
pattern_metadata JSONB         NULLABLE   -- {points, ratios, quality_score, prz_high, prz_low}
```

**`backtest_runs` table:**
```sql
primary_tf   VARCHAR(10)   NOT NULL DEFAULT 'M15'
context_tfs  JSONB         NOT NULL DEFAULT '[]'
```

**Alembic migration**: add 4 columns with NULL defaults.

---

## 6. Analytics Backend

### 6.1 New Endpoints

```
GET /api/v1/backtest/runs/{run_id}/analytics
    → { kpis, schema_type, panel_type, group_by }

GET /api/v1/backtest/runs/{run_id}/analytics/heatmap?axis1=symbol&axis2=pattern_name&metric=win_rate
    → { labels_x, labels_y, values: float[][] }

GET /api/v1/backtest/runs/{run_id}/analytics/combinations?limit=10
    → { top: [...], worst: [...], recommendations: [str] }

GET /api/v1/backtest/runs/{run_id}/analytics/groups
    → { groups: [{ name, trades, win_rate, profit_factor, total_pnl, avg_win, avg_loss, best_symbol }] }
```

### 6.2 Analytics Service

**File**: `backend/services/backtest_analytics.py`

```python
def aggregate_by_group(trades: list[BacktestTrade], group_by: str) -> list[GroupStats]
def build_heatmap(trades, axis1: str, axis2: str, metric: str) -> HeatmapData
def generate_recommendations(heatmap: HeatmapData, top_n: int = 3) -> list[str]
    # Example output: "Best combo: XAUUSD + Bat (68% WR, 2.1 PF). Avoid: GBPJPY + Butterfly (32% WR)."
def compute_kpis(trades: list[BacktestTrade], run: BacktestRun) -> KPIData
```

`group_by` comes from `strategy.analytics_schema()["group_by"]` — the backend reads it from the run's strategy.

---

## 7. Analytics Frontend

### 7.1 New Route

`/frontend/src/app/backtest/[id]/analytics/page.tsx`

Linked from existing backtest results page ("View Analytics" button on completed runs).

### 7.2 Global Shell Components (always rendered)

```
frontend/src/components/analytics/
├── analytics-kpi-bar.tsx          # Trades | WR | PF | Drawdown | P&L | Sharpe
├── analytics-heatmap.tsx          # Symbol × Group colored grid (Recharts or custom SVG)
├── analytics-combinations.tsx     # Top 10 / Worst 10 side-by-side tables
└── analytics-recommendations.tsx  # Auto-generated text chips
```

### 7.3 Strategy Detail Panels

```
frontend/src/components/analytics/panels/
├── pattern-grid-panel.tsx         # RuleOnly → harmonic/SMC/CRT pattern cards
├── llm-confidence-panel.tsx       # LLMOnly → confidence histogram + cost/trade
├── rule-trigger-panel.tsx         # RuleThenLLM → trigger rate + accept rate + cost saved
├── validator-panel.tsx            # HybridValidator → saves counter + hold outcomes
└── consensus-panel.tsx            # MultiAgent → agreement rate + disagreement breakdown
```

Panel selection logic (frontend):
```typescript
const PANEL_MAP: Record<string, React.ComponentType> = {
  pattern_grid: PatternGridPanel,
  llm_confidence: LLMConfidencePanel,
  rule_trigger: RuleTriggerPanel,
  validator: ValidatorPanel,
  consensus: ConsensusPanel,
}

// analytics API returns panel_type from strategy.analytics_schema()
const Panel = PANEL_MAP[analyticsData.panel_type]
```

### 7.4 Pattern Grid Panel Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  Pattern Performance Overview                                    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  Shark   │  │ Butterfly│  │ Gartley  │  │   Bat    │        │
│  │ 45 trades│  │ 32 trades│  │ 28 trades│  │ 24 trades│        │
│  │ Best: XAU│  │ Best: GBJ│  │ Best: EUR│  │ Best: GBU│        │
│  │ WR: 62%  │  │ WR: 58%  │  │ WR: 51%  │  │ WR: 49%  │        │
│  │ PF: 1.8  │  │ PF: 1.5  │  │ PF: 1.2  │  │ PF: 1.1  │        │
│  │ P&L: +$X │  │ P&L: +$X │  │ P&L: +$X │  │ P&L: +$X │        │
│  │ Avg W/L  │  │ Avg W/L  │  │ Avg W/L  │  │ Avg W/L  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                       │
│  │  Cypher  │  │   Crab   │  │   ABCD   │                       │
│  │ ...      │  │ ...      │  │ ...      │                       │
│  └──────────┘  └──────────┘  └──────────┘                       │
└──────────────────────────────────────────────────────────────────┘
```

Card click → drill-down drawer showing all trades for that pattern (symbol, direction, entry/exit, P&L, pattern metadata).

### 7.5 Full Page Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  [KPI Bar: Total Trades | Win Rate | Profit Factor | Max DD | P&L]│
├──────────────────────────────────────────────────────────────────┤
│  [Heatmap: Symbol × Pattern — colored by win_rate or total_pnl]  │
│   Metric toggle: Win Rate | P&L | Profit Factor                  │
├───────────────────────────┬──────────────────────────────────────┤
│  Top 10 Combinations      │  Worst 10 Combinations              │
│  Symbol+Pattern | WR | PF │  Symbol+Pattern | WR | PF           │
│  ...                      │  ...                                 │
├───────────────────────────┴──────────────────────────────────────┤
│  Recommendations                                                 │
│  "Best: XAUUSD + Bat (68% WR, 2.1 PF)"                         │
│  "Avoid: GBPJPY + Butterfly (32% WR, 0.7 PF)"                  │
├──────────────────────────────────────────────────────────────────┤
│  [Strategy Detail Panel — selected by panel_type]               │
│  e.g. Pattern Grid for RuleOnly Harmonic                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 8. Build Priority Order

1. **MTF Data Layer** — `mtf_data.py` + `mtf_backtest_loader.py` — everything depends on this
2. **Strategy Base Classes** — 5 typed bases + DB migration for `execution_mode`
3. **Harmonic Pattern Engine** — `swing_detector` → `patterns/` → `pattern_scanner` → `prz_calculator` → `harmonic_strategy`
4. **Backtest Engine Updates** — MTF support + `pattern_name`/`pattern_metadata` storage
5. **Analytics Backend** — aggregation service + 4 new API endpoints
6. **Analytics Frontend** — global shell → panel components → pattern grid panel
7. **LLMOnly + RuleThenLLM + MultiAgent types** — progressive: Type 2 first, then Types 4 & 5
8. **Additional Rule-Only Strategies** — SMC, CRT, RSI/Fibo/Stochastic (user adds later using RuleOnlyStrategy base)

---

## 9. Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| MTF data packaging | Primary TF + declared context TFs | Self-documenting, no over-fetching, clean backtest alignment |
| Strategy type architecture | 5 typed base classes (Option C) | Each type owns its orchestration; no conditional spaghetti in engine |
| DB strategy_type field | Rename to execution_mode (5 values) | Matches code; old config/prompt/code distinction absorbed into class hierarchy |
| Swing point detection | Williams Fractals n=2 | Non-repainting; industry standard; realistic backtests |
| Pattern tolerance | ±5% on all ratios | Industry standard; configurable per instance |
| Signal timing | M15 candle close where D pivot confirms | Non-repainting; consistent with all other strategy types |
| Analytics panel selection | panel_type from analytics_schema() | Strategy owns its display contract; frontend decoupled from type logic |
| SL placement | Beyond X point + 0.5×ATR(14) | Standard harmonic invalidation level; ATR adapts to volatility |
| TP levels | 0.382 and 0.618 CD retracements | Standard harmonic targets; two levels for partial close optionality |
