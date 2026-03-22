# Backtest System — Visual Trade Integration & Engine Quality Plan

**Created:** 2026-03-22
**Scope:** All backtest improvements from audit — visual trade chart overlay, engine refactors, analytics chart tab, drawdown chart.

---

## Phase 0: Documentation Discovery (DONE — pre-read findings)

### Confirmed APIs

**lightweight-charts v5.1.0** (`frontend/node_modules/lightweight-charts/dist/typings.d.ts`):
```ts
// PUBLIC API for markers (v5 — NOT series.setMarkers() directly)
import { createSeriesMarkers } from 'lightweight-charts';

const markersPlugin = createSeriesMarkers(series, markers, options?);
markersPlugin.setMarkers([...]);   // update markers
markersPlugin.markers();           // read current markers

// SeriesMarker shape
interface SeriesMarker<T> {
  time: T;                 // UTCTimestamp
  position: 'aboveBar' | 'belowBar' | 'inBar';
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown';
  color: string;
  text?: string;
  size?: number;
}
```

**TradingChart existing pattern** (`frontend/src/components/chart/trading-chart.tsx`):
- Effects numbered 1–6, each using `useRef` + `useEffect`
- Price lines via `series.createPriceLine()` stored in `priceLinesRef`
- New markers follow the same ref+effect pattern as Effect 2 (price lines)
- `seriesRef.current` is the candlestick series to attach markers to

**Backtest DB** (`backend/db/models.py`):
- `BacktestRun`: has `symbol`, `timeframe`, `start_date`, `end_date`, `primary_tf` — no `data_file_path` (gap)
- `BacktestTrade`: has `entry_time`, `exit_time`, `entry_price`, `exit_price`, `direction`, `profit`, `stop_loss`, `take_profit`, `exit_reason`, `pattern_name`

**Critical gap**: Candle data is loaded from CSV/MT5 into memory during the run but **not persisted**. The candles are discarded after the run completes. A new endpoint + storage mechanism is needed for chart replay.

**Existing candle API**: `GET /market-data/{symbol}/{timeframe}` (live MT5 only, not historical range).

**No existing `GET /backtest/runs/{run_id}/candles` endpoint.**

---

## Phase 1 — Backend: Persist Candles + New Candles Endpoint

**Goal**: Give the frontend a way to retrieve the historical OHLCV candles used in a backtest run, enabling chart replay.

### 1.1 — Add `data_file_path` to `BacktestRun` model

**File**: `backend/db/models.py`

Add one column to `BacktestRun`:
```python
data_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
# Absolute path to the stored OHLCV CSV for this run (enables chart replay).
# None for MT5 runs (re-fetched on demand).
```

### 1.2 — Alembic migration

**New file**: `backend/alembic/versions/<hash>_add_data_file_path_to_backtest_runs.py`

```python
def upgrade():
    op.add_column('backtest_runs', sa.Column('data_file_path', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('backtest_runs', 'data_file_path')
```

### 1.3 — Persist CSV during backtest job

**File**: `backend/api/routes/backtest.py`, function `_run_backtest_job`

After loading candles from CSV (line ~454), copy the file to a permanent location:
```python
import shutil, pathlib

CANDLE_STORE = pathlib.Path("uploads/candles")
CANDLE_STORE.mkdir(parents=True, exist_ok=True)

dest = CANDLE_STORE / f"{run_id}.csv"
shutil.copy(primary_upload, dest)
run.data_file_path = str(dest)
await db.commit()
```

For MT5 runs, leave `data_file_path = None` (re-fetch on demand).

### 1.4 — New GET endpoint: `/backtest/runs/{run_id}/candles`

**File**: `backend/api/routes/backtest.py`

Add after the equity-curve endpoint (~line 265):
```python
@router.get("/runs/{run_id}/candles")
async def get_candles(run_id: int, db: AsyncSession = Depends(get_db)):
    """Return OHLCV candles for a backtest run (for chart replay).

    CSV runs: reads the stored file at run.data_file_path.
    MT5 runs: re-fetches from MT5 using run.symbol / timeframe / date range.
    Returns list of {time, open, high, low, close, volume}.
    """
```

Response shape (matches `OHLCVCandle` in TradingChart):
```python
[{"time": int, "open": float, "high": float, "low": float, "close": float, "volume": float}]
```

### 1.5 — Frontend API client

**File**: `frontend/src/lib/api.ts`, in `backtestApi` object:
```ts
getCandles: (runId: number) =>
  apiRequest<OHLCVCandle[]>(`/backtest/runs/${runId}/candles`),
```

**Verification checklist:**
- [ ] `uv run alembic upgrade head` succeeds
- [ ] POST to `/backtest/runs` + run → `data_file_path` populated in DB for CSV runs
- [ ] `GET /backtest/runs/{id}/candles` returns array of OHLCV objects

**Anti-patterns:**
- Do NOT store candles in PostgreSQL (too large — stays as file)
- Do NOT block the backtest job on file copy errors (log warning, continue)

---

## Phase 2 — Frontend: TradingChart Trade Marker Support

**Goal**: Add a `tradeMarkers` prop to `TradingChart` that renders entry/exit arrows using `createSeriesMarkers`.

### 2.1 — Add `TradeMarker` type

**File**: `frontend/src/types/trading.ts`

```ts
export interface TradeMarker {
  entry_time: number;      // unix timestamp (seconds)
  exit_time: number | null;
  direction: "BUY" | "SELL";
  profit: number | null;
  exit_reason: string | null;
}
```

### 2.2 — Update `TradingChartProps`

**File**: `frontend/src/components/chart/trading-chart.tsx`

Add to imports:
```ts
import { createSeriesMarkers, type ISeriesMarkersPluginApi } from 'lightweight-charts';
import type { TradeMarker } from '@/types/trading';
```

Add to `TradingChartProps`:
```ts
tradeMarkers?: TradeMarker[];
```

Add ref inside component:
```ts
const markersPluginRef = useRef<ISeriesMarkersPluginApi<UTCTimestamp> | null>(null);
```

**Cleanup in Effect 1 (symbol change → destroy chart)**:
```ts
markersPluginRef.current = null;  // plugin detaches with chart
```

### 2.3 — Add Effect 7: manage trade markers

Follow the exact pattern of Effect 2 (price lines). Add after Effect 6 (RSI pane):

```ts
// ── Effect 7: trade markers (backtest replay) ──────────────────────────────
useEffect(() => {
  const series = seriesRef.current;
  if (!series) return;

  // Clear previous markers
  if (markersPluginRef.current) {
    markersPluginRef.current.setMarkers([]);
  }

  if (!tradeMarkers || tradeMarkers.length === 0) return;

  const markers = tradeMarkers.flatMap((t): SeriesMarker<UTCTimestamp>[] => {
    const isBuy = t.direction === "BUY";
    const isWin = (t.profit ?? 0) >= 0;

    const entry: SeriesMarker<UTCTimestamp> = {
      time: t.entry_time as UTCTimestamp,
      position: isBuy ? 'belowBar' : 'aboveBar',
      shape: isBuy ? 'arrowUp' : 'arrowDown',
      color: isBuy ? '#22c55e' : '#ef4444',
      text: isBuy ? 'B' : 'S',
      size: 1,
    };

    if (!t.exit_time) return [entry];

    const exit: SeriesMarker<UTCTimestamp> = {
      time: t.exit_time as UTCTimestamp,
      position: isBuy ? 'aboveBar' : 'belowBar',
      shape: 'circle',
      color: isWin ? '#22c55e' : '#ef4444',
      text: t.exit_reason === 'sl' ? 'SL' : t.exit_reason === 'tp' ? 'TP' : 'X',
      size: 1,
    };

    return [entry, exit];
  });

  // Sort by time (required by lightweight-charts)
  markers.sort((a, b) => (a.time as number) - (b.time as number));

  if (!markersPluginRef.current) {
    markersPluginRef.current = createSeriesMarkers(series as ISeriesApi<'Candlestick', UTCTimestamp>, markers);
  } else {
    markersPluginRef.current.setMarkers(markers);
  }
}, [tradeMarkers]);
```

**Verification checklist:**
- [ ] `npm run build` passes — no TypeScript errors
- [ ] `createSeriesMarkers` imported from `'lightweight-charts'` (not invented)
- [ ] Effect cleanup: `setMarkers([])` called on symbol change (Effect 1 cleanup)
- [ ] Markers sorted by time before calling `setMarkers` (required by lw-charts)

**Anti-patterns:**
- Do NOT call `series.setMarkers()` directly — that was v4 API, does not exist in v5
- Do NOT create a new `createSeriesMarkers()` on every render — use the `markersPluginRef` pattern

---

## Phase 3 — Frontend: Backtest Results "Chart" Tab

**Goal**: Add a "Chart" tab to `BacktestResults` that shows `TradingChart` with trade markers.

### 3.1 — Add "Chart" tab to `BacktestResults`

**File**: `frontend/src/components/backtest/backtest-results.tsx`

Add `"chart"` to `TabId`:
```ts
type TabId = "equity" | "monthly" | "trades" | "chart";
```

Add tab entry:
```ts
{ id: "chart", label: "Chart" },
```

Add candles state:
```ts
const [candles, setCandles] = useState<OHLCVCandle[]>([]);
const [candlesLoading, setCandlesLoading] = useState(false);
```

Add lazy-load: only fetch candles when Chart tab is first activated:
```ts
useEffect(() => {
  if (activeTab !== "chart" || candles.length > 0) return;
  setCandlesLoading(true);
  backtestApi.getCandles(run.id)
    .then(setCandles)
    .catch(() => {/* silently show empty chart */})
    .finally(() => setCandlesLoading(false));
}, [activeTab, run.id, candles.length]);
```

### 3.2 — Render TradingChart in Chart tab

Convert `BacktestTrade` → `TradeMarker` inline:
```tsx
{activeTab === "chart" && (
  <div className="h-[500px] w-full">
    {candlesLoading ? (
      <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
        Loading candles...
      </div>
    ) : (
      <TradingChart
        candles={candles}
        positions={[]}
        pendingOrders={[]}
        symbol={run.symbol}
        viewResetKey={`backtest-${run.id}`}
        tradeMarkers={trades.map(t => ({
          entry_time: new Date(t.entry_time).getTime() / 1000,
          exit_time: t.exit_time ? new Date(t.exit_time).getTime() / 1000 : null,
          direction: t.direction as "BUY" | "SELL",
          profit: t.profit ?? null,
          exit_reason: t.exit_reason ?? null,
        }))}
      />
    )}
  </div>
)}
```

**Verification checklist:**
- [ ] "Chart" tab appears in results view
- [ ] Candles load lazily (only on first tab activation)
- [ ] Trade markers render as arrows on the candlestick chart
- [ ] Empty state shows when candles endpoint returns 404/empty

**Anti-patterns:**
- Do NOT eagerly load candles on run load — large datasets block the initial render
- Do NOT pass live `positions` or `pendingOrders` to the backtest chart

---

## Phase 4 — Frontend: Row-Click → Chart Scroll

**Goal**: Clicking a trade row in the table scrolls the chart to that candle's timeframe position.

### 4.1 — Add `focusTime` prop to `TradingChart`

**File**: `frontend/src/components/chart/trading-chart.tsx`

Add to `TradingChartProps`:
```ts
focusTime?: number;  // unix timestamp — chart scrolls to this time when it changes
```

Add Effect 8:
```ts
// ── Effect 8: scroll chart to a specific time (row-click from trade table) ──
useEffect(() => {
  if (!focusTime || !chartRef.current) return;
  chartRef.current.timeScale().scrollToPosition(
    chartRef.current.timeScale().timeToCoordinate(focusTime as UTCTimestamp) ?? 0,
    true // animated
  );
}, [focusTime]);
```

Actually `scrollToPosition` takes an index offset, not pixels. The correct API is:
```ts
chartRef.current.timeScale().scrollToRealTime();
// or set visible range:
const barsBefore = 10;
chartRef.current.timeScale().setVisibleRange({
  from: (focusTime - barsBefore * avgBarSeconds) as UTCTimestamp,
  to: (focusTime + barsBefore * avgBarSeconds) as UTCTimestamp,
});
```

Simpler: use `scrollToPosition` with the logical index approach is complex. Use `setVisibleLogicalRange` centered around the target bar instead. Reference the existing `fitContent()` call pattern in Effect 1b for how to safely call time scale methods.

### 4.2 — Wire `focusTime` in `BacktestResults`

**File**: `frontend/src/components/backtest/backtest-results.tsx`

Add state:
```ts
const [focusTime, setFocusTime] = useState<number | undefined>();
```

Pass to `BacktestTradeTable`:
```tsx
<BacktestTradeTable trades={trades} onRowClick={(t) => {
  setFocusTime(new Date(t.entry_time).getTime() / 1000);
  setActiveTab("chart");  // switch to chart tab
}} />
```

Pass `focusTime` to `TradingChart`.

### 4.3 — Add `onRowClick` to `BacktestTradeTable`

**File**: `frontend/src/components/backtest/backtest-trade-table.tsx`

Add to `Props`:
```ts
onRowClick?: (trade: BacktestTrade) => void;
```

Add `onClick` + hover cursor to `<TableRow>`:
```tsx
<TableRow
  key={t.id}
  className={cn("cursor-pointer hover:bg-muted/50", onRowClick && "cursor-pointer")}
  onClick={() => onRowClick?.(t)}
>
```

**Verification checklist:**
- [ ] Clicking a row switches to "Chart" tab
- [ ] Chart scrolls to the entry candle of the clicked trade
- [ ] Table rows show pointer cursor when `onRowClick` is provided

---

## Phase 5 — Frontend: Analytics Page Chart Tab

**Goal**: Add a price chart with trade markers to the analytics page (`/backtest/[id]/analytics`).

### 5.1 — Add chart state + fetch to analytics page

**File**: `frontend/src/app/backtest/[id]/analytics/page.tsx`

Add state:
```ts
const [candles, setCandles] = useState<OHLCVCandle[]>([]);
const [trades, setTrades] = useState<BacktestTrade[]>([]);
const [chartTab, setChartTab] = useState(false);
```

Lazy-fetch on chart tab activation (same pattern as Phase 3).

### 5.2 — Add "Chart" section below KPI bar

Render a collapsible / tabbed section with `TradingChart` + trade markers:
```tsx
<div className="border rounded-lg">
  <button onClick={() => setChartTab(v => !v)} className="...">
    Price Chart with Trade Markers
  </button>
  {chartTab && (
    <div className="h-[600px]">
      <TradingChart candles={candles} tradeMarkers={...} ... />
    </div>
  )}
</div>
```

**Verification checklist:**
- [ ] Analytics page has chart section (collapsed by default)
- [ ] Expanding loads candles lazily
- [ ] All trades from the run appear as markers on the chart

---

## Phase 6 — Backend: Engine Quality Improvements

**Goal**: Replace raw dicts in `BacktestEngine` with typed dataclasses. Move shared instrument logic to a utility.

### 6.1 — `OpenPosition` and `TradeResult` dataclasses

**File**: `backend/services/backtest_engine.py` (top of file, before class)

```python
from dataclasses import dataclass, field

@dataclass
class OpenPosition:
    symbol: str
    direction: str          # "BUY" | "SELL"
    entry_time: int         # unix timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float
    take_profit_levels: list[float] | None = None
    tp_level_idx: int = 0
    pattern_name: str | None = None
    pattern_metadata: str | None = None

@dataclass
class TradeResult:
    symbol: str
    direction: str
    entry_time: int
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float
    exit_time: int
    exit_price: float
    exit_reason: str
    profit: float
    equity_after: float
    pattern_name: str | None = None
    pattern_metadata: str | None = None
```

Replace `open_position = { ... }` dict construction with `OpenPosition(...)`.
Replace trade dict assembly with `dataclasses.asdict(TradeResult(...))` — keeps the dict output contract for DB persistence.

### 6.2 — Move `_contract_size()` to shared utility

**New file**: `backend/services/instrument_spec.py`

```python
def contract_size(symbol: str) -> float:
    """Standard lot contract size for a symbol."""
    ...  # Move the existing logic from backtest_engine._contract_size()
```

**Files to update:**
- `backend/services/backtest_engine.py` — import from `instrument_spec`
- `backend/mt5/executor.py` — replace any hardcoded contract size logic

**Verification checklist:**
- [ ] `uv run pytest -v` passes all backtest tests
- [ ] `contract_size("XAUUSD")` returns 100
- [ ] `contract_size("EURUSD")` returns 100_000
- [ ] No references to `_contract_size` remain in engine

---

## Phase 7 — Frontend: Drawdown Chart

**Goal**: Add a drawdown-over-time chart to the backtest results equity tab.

### 7.1 — Backend: Drawdown series endpoint

**File**: `backend/api/routes/backtest.py`

Add endpoint:
```python
@router.get("/runs/{run_id}/drawdown")
async def get_drawdown(run_id: int, db: AsyncSession = Depends(get_db)):
    """Return [{time, drawdown_pct}] from the equity curve."""
```

Logic: load `BacktestRun.initial_balance` + equity curve trades ordered by time.
Calculate running peak, drawdown = (peak - equity) / peak * 100.

### 7.2 — Frontend: `DrawdownChart` component

**New file**: `frontend/src/components/backtest/drawdown-chart.tsx`

- Re-use the existing `EquityCurveChart` structure (Recharts `AreaChart` with red fill)
- Y-axis: negative drawdown percentage (0% at top, -20% at bottom)
- Source pattern: copy from `equity-curve-chart.tsx`

### 7.3 — Add to `BacktestResults` equity tab

Add below `EquityCurveChart` (or as a secondary chart in the same tab):
```tsx
{activeTab === "equity" && (
  <>
    <EquityCurveChart data={equity} initialBalance={run.initial_balance} />
    <DrawdownChart runId={run.id} />
  </>
)}
```

**Verification checklist:**
- [ ] `GET /backtest/runs/{id}/drawdown` returns `[{time, drawdown_pct}]`
- [ ] Chart shows max drawdown correctly (matches `BacktestRun.max_drawdown_pct`)
- [ ] Red fill visually distinct from equity curve

---

## Phase 8 — Backend: Backtest Run Config Improvements

**Goal**: Add configurable `commission_per_lot` and `tp_partial_close_ratio` to backtest runs.

### 8.1 — Add fields to `BacktestRunRequest` Pydantic model

**File**: `backend/api/routes/backtest.py`

```python
commission_per_lot: float = Field(default=0.0, ge=0)  # USD per lot (round trip)
tp_partial_close_ratio: float = Field(default=0.5, gt=0, le=1)  # fraction to close at each TP
```

### 8.2 — Add columns to `BacktestRun` model

**File**: `backend/db/models.py`

```python
commission_per_lot: Mapped[float] = mapped_column(Float, default=0.0)
tp_partial_close_ratio: Mapped[float] = mapped_column(Float, default=0.5)
```

Migration needed: `add_commission_and_partial_tp_to_backtest_runs`.

### 8.3 — Wire into engine

**File**: `backend/services/backtest_engine.py`

- Accept `commission_per_lot` in config dict
- Subtract `commission_per_lot * volume` from profit on each trade close
- Accept `tp_partial_close_ratio` and use instead of hardcoded `0.5` in partial close logic

### 8.4 — Frontend: Add fields to `BacktestConfigForm`

**File**: `frontend/src/components/backtest/backtest-config-form.tsx`

Add two new numeric inputs with defaults and labels.

**Verification checklist:**
- [ ] Default run with `commission_per_lot=0` produces same results as before
- [ ] `tp_partial_close_ratio=0.33` closes 1/3 at each TP level

---

## Execution Order

| Phase | Title | Effort | Impact |
|-------|-------|--------|--------|
| 1 | Candles persistence + endpoint | Medium | Blocker for phases 3/5 |
| 2 | TradingChart marker support | Small | Blocker for phases 3/5 |
| 3 | Backtest Results chart tab | Small | High UX |
| 4 | Row-click → chart scroll | Small | High UX |
| 5 | Analytics page chart tab | Small | High UX |
| 6 | Engine typed dataclasses | Medium | Code quality |
| 7 | Drawdown chart | Small | Analytics |
| 8 | Commission + partial TP config | Medium | Engine accuracy |

**Recommended execution**: Phases 1 → 2 → 3 → 4 (together, one session). Then 5 → 7 (one session). Then 6 → 8 (backend-only session).
