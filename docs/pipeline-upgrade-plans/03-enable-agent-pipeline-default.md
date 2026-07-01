# Plan 03: Enable 4-Agent Pipeline (Mode B) by Default

**Branch:** `feature/agent-pipeline-default`
**Depends on:** nothing, but plan 05 (ensemble/quorum) depends on this.
**Risk:** medium — changes the decision path for every live signal.

## Goal

The user's mental model of the pipeline (news → market analysis →
indicator/pattern/trend agents → execution decision) assumed Mode B was
already the running mode. It isn't — Mode A (3-role sequential,
`market_analysis → execution_decision`, no sub-agents) is the default.
Flip the default to Mode B and verify it end-to-end before relying on it.

## Steps

1. Locate the exact current default and override mechanism for
   `enable_agent_pipeline` (and `enable_indicator_agent`/
   `enable_pattern_agent`/`enable_trend_agent`) — confirm whether this is a
   single global `core/config.py` setting, a `GlobalSettings` DB row, or a
   per-strategy override (memory suggests a `strategy_overrides` dict is
   used elsewhere for things like `news_filter` — confirm if agent-pipeline
   toggles follow the same per-strategy pattern before assuming a single
   global flip is sufficient).
2. Flip the default to `True` following whatever pattern step 1 confirms —
   same "don't silently overwrite an explicit existing value" caution as
   plan 02's news flag.
3. **Before flipping in production**: run a manual test on a demo account
   for at least one full scheduled cycle per timeframe you use (M15/H1/
   H4/D1), confirming via `pipeline_runs`/`pipeline_steps` (the
   `PipelineTracer` tables) that `indicator_agent`, `pattern_agent`, and
   `trend_agent` steps actually appear and complete without error, and
   that `decision_node` correctly reconciles their outputs into a final
   signal.
4. Check LLM cost impact before flipping live — Mode B makes 3 additional
   parallel LLM calls per signal versus Mode A's single execution_decision
   call. Pull recent `llm_calls` cost data for Mode A signals and estimate
   the 3x-ish multiplier per signal; confirm this is acceptable given your
   current per-account/per-strategy call volume (tie into plan 06's cost
   tracking work if it's already landed).
5. Confirm the dashboard/pipeline-trace UI actually renders the extra
   steps clearly (this is presumably part of what the user meant by
   "should be able to check every edge case" — if indicator/pattern/trend
   steps aren't visually distinguished from market_analysis in the trace
   view today, that's a small frontend fix worth bundling here since it's
   directly related).

## Acceptance criteria

- New/default deploys run Mode B without any manual settings change.
- A full pipeline run trace for a real symbol shows all three sub-agent
  steps plus `decision_node`, viewable on the dashboard.
- Cost delta from switching is measured and acknowledged, not just
  assumed acceptable.
- `uv run pytest -v` passes, including whatever existing tests cover
  `run_agent_pipeline()`/`build_pipeline()` in `ai/agent_pipeline.py`.

## Post-implementation note (what already existed vs. what was built)

Verified before writing code, per the lesson from sibling plans 01/02 that
these docs can be stale:

1. **`enable_agent_pipeline` is a single global flag, not per-strategy.**
   `core/config.py` (in-memory `Settings`) + a `GlobalSettings` DB row
   (`db/models.py:309`), loaded at startup in `main.py` only if the row
   already exists. No `strategy_overrides`-style per-strategy mechanism
   exists for this flag — confirmed by grepping every reference across
   the backend. The sub-agent toggles (`enable_indicator_agent`/
   `enable_pattern_agent`/`enable_trend_agent`) already defaulted to
   `True` in both `core/config.py` and the DB model — only the master
   toggle needed flipping.
2. **The trend-agent wiring the plan worried about is already correct.**
   `run_agent_pipeline()` (`ai/orchestrator/_pipeline.py:520-713`)
   internally generates `trendline_chart_b64` from OHLCV via
   `fit_trendlines()`/`render_trendline_chart()` whenever a base chart
   image is available and OHLCV has ≥50 candles — the caller doesn't need
   to supply it separately. So as long as `chart_b64` is populated (gated
   by `enable_chart_vision`, default `True`) and OHLCV has enough candles,
   indicator/pattern/trend all get real inputs by default. No production
   wiring gap found.
3. **The pipeline-trace UI already visually distinguishes every sub-agent
   step.** `frontend/src/components/logs/pipeline-step-card.tsx` has
   distinct `STEP_LABELS` for `indicator_agent_llm`/`pattern_agent_llm`/
   `trend_agent_llm`/`execution_decision_llm`, each with its own token
   usage, model/provider badge, and cost display. Step 5 of this plan
   (UI fix) was unnecessary — skipped.
4. **A settings UI toggle for `enable_agent_pipeline` already exists**
   (`frontend/src/components/settings/agent-pipeline-section.tsx`) — no
   frontend work needed there either.

### Actual changes on this branch

- `backend/core/config.py` — `enable_agent_pipeline` default → `True`.
- `backend/db/models.py` — `GlobalSettings.enable_agent_pipeline` column
  default → `True` (matches the in-memory default, avoiding the same
  "lazily-created row pins the old default" bug plan 02 found and fixed
  for `news_enabled`).
- `backend/tests/test_agent_pipeline.py` — new
  `test_pipeline_all_agents_enabled_end_to_end`: runs the full graph with
  all three sub-agents enabled and both chart images present (the
  realistic default-config case), asserting every node executes, every
  report is populated, and token usage is recorded for the cost dashboard
  on every step. This is the closest verification available without live
  MT5/LLM access.

### Cost-multiplier estimate (analytical, no live cost data available in this sandbox)

Per signal:
- **Mode A**: 2 LLM calls (`market_analysis`, `execution_decision`) +
  1 optional (`chart_vision`, gated by `enable_chart_vision`) ≈ 2-3 calls.
- **Mode B**: `market_analysis` (1) + `indicator_agent`/`pattern_agent`/
  `trend_agent` (3, parallel) + `decision_node`/`execution_decision`
  equivalent (1) = **5 calls**, roughly **2x Mode A's cost** when Mode A
  already had chart vision on, or **~2.5x** if it didn't. This is lower
  than the plan's original "3x-ish" guess because Mode A already made a
  chart_vision call in most configurations. Real confirmation still
  needs live `llm_calls` data once this runs against a real account —
  recommend checking this against plan 06's cost dashboard once both are
  live, per the plan's own step 4.

### Not verified (needs a human + Windows/MT5 + demo account)

- Live demo-account runs across each timeframe you use (M15/H1/H4/D1),
  confirming `pipeline_runs`/`pipeline_steps` show all three sub-agent
  steps completing without error against real market data and a real LLM
  provider — this sandbox has no MT5 and no live LLM credentials.
- Real cost delta measurement (the analytical estimate above is a
  starting point, not a substitute for actual `llm_calls` data).
