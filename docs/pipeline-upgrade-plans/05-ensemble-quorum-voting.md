# Plan 05: Ensemble/Quorum Voting Across Sub-Agents

**Branch:** `feature/ensemble-quorum`
**Depends on:** 03 (Mode B must be the running default).
**Risk:** medium — changes when/whether `execution_decision` gets called.

## Goal

Today, `indicator_agent`/`pattern_agent`/`trend_agent` produce free-text
analysis that `decision_node` reconciles into one call to
`execution_decision`. There's no explicit agreement/disagreement signal —
a confidently-wrong single agent can dominate the final decision as easily
as a genuine 3-way consensus. Add an explicit vote + quorum check.

## Steps

1. Change each sub-agent's output schema to include a structured vote:
   `direction: BUY | SELL | HOLD` and `confidence: float` alongside their
   existing free-text rationale (Pydantic model, same pattern as
   `TradingSignal`).
2. In `decision_node` (`ai/agent_pipeline.py`), compute agreement before
   calling `execution_decision`:
   - **≥2/3 agree** on a non-HOLD direction → pass the full vote breakdown
     (all three directions + confidences + rationale) into
     `execution_decision`'s context, so the final LLM call is informed by
     the disagreement/agreement pattern, not just raw text.
   - **<2/3 agree** (all three disagree, or split with no majority) →
     short-circuit to HOLD directly, **skip the `execution_decision` LLM
     call entirely**. Low agreement means a weak setup; this also saves
     one LLM call per low-conviction signal, offsetting some of the extra
     cost Mode B introduced in plan 03.
3. Persist the vote breakdown in the pipeline trace (`PipelineTracer`) so
   it's auditable after the fact — "why did we HOLD here" should be
   answerable from the dashboard without digging into logs.
4. Decide unanimous-HOLD handling: if all three vote HOLD, that's
   agreement, not disagreement — still call `execution_decision` (or skip
   it as a cost optimization, since 3x HOLD is unlikely to flip to a
   trade) — recommend skipping, but confirm this doesn't remove a case
   where `execution_decision` has historically overridden a HOLD
   consensus into a trade (check pipeline history before assuming this
   never happens).

## Acceptance criteria

- Vote schema present in `pipeline_steps` for indicator/pattern/trend
  steps, visible on the dashboard trace.
- A test case with 2/3 agreement passes vote context into
  `execution_decision` and asserts the call happens.
- A test case with full disagreement asserts `execution_decision` is
  **not** called and the signal resolves to HOLD.
- Cost per signal decreases for low-agreement cases (spot-check against
  `llm_calls` — fewer execution_decision calls after this lands).
- `uv run pytest -v` passes.
