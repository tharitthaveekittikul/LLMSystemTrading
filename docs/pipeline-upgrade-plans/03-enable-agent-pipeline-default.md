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
