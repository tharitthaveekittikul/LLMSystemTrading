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

## Post-implementation note (what was built, and where it deviates from the plan)

### Deliberate deviation from step 1: no sub-agent prompt/schema changes

Step 1 asked to change each sub-agent's own output schema (a Pydantic
model with `direction`/`confidence` fields, like `TradingSignal`). Instead,
votes are derived in Python from each sub-agent's **existing** free-form
fields, with no LLM prompt changes at all:

- `indicator_agent`'s `overall` (bullish/bearish/neutral) → BUY/SELL/HOLD
- `pattern_agent`'s `bias` (bullish/bearish/neutral) → BUY/SELL/HOLD
- `trend_agent`'s `trend_prediction` (upward/downward/sideways) → BUY/SELL/HOLD
- All three already report `confidence` as `low|medium|high` — mapped to
  `0.3/0.6/0.9`.

Reasoning: changing three LLM prompts means re-validating their output
format against real model behavior, which is a bigger blast radius than a
pure-Python normalization layer over fields that already exist and are
already displayed on the dashboard unchanged. This is a lower-risk way to
get the same quorum signal. `ai/agent_pipeline.py`: `_indicator_vote`,
`_pattern_vote`, `_trend_vote`, `_confidence_to_float`, `_extract_vote`.

### Quorum rule actually implemented (generalizes the plan's "2/3")

`_quorum_verdict()`: with fewer than `MIN_VOTERS_FOR_QUORUM = 2` available
votes (an agent disabled or its call failed), there's nothing meaningful
to vote on, so `execution_decision` always runs as before. Otherwise, a
**strict majority** among available voters — `len(votes)//2 + 1`, which is
2 of 3 or 2 of 2 — on **any** direction, including HOLD, counts as
agreement and `execution_decision` runs, given the vote breakdown as
extra context (`decision_agent.py`'s `vote_summary` param). Only a
genuine split with no majority (e.g. 1 BUY / 1 SELL / 1 HOLD among 3
voters) skips `execution_decision` entirely and short-circuits straight
to a `HOLD` signal with `decision_tokens=None` (zero cost for that step).

This directly resolves step 4's open question: **unanimous/majority HOLD
is treated as agreement and `execution_decision` still runs** — I did not
skip it, because I have no way in this sandbox to check "does
`execution_decision` ever override a HOLD consensus into a trade" against
real pipeline history, which the plan itself said to confirm before
skipping. Skipping the call in this case remains available as a future
optimization once that's verified against real data.

### Auditability

`decision_agent.py` now takes an optional `vote_summary` param and
appends it to its own prompt when present, so the final decision LLM
sees the vote breakdown. `LLMAnalysisResult.vote_summary` (new field)
carries it through `run_agent_pipeline()`, and
`services/ai_trading/_signal.py`'s `execution_decision_llm` pipeline-step
recording now includes `vote_summary` in `input_data` whenever present —
visible in the existing pipeline-trace UI without any frontend changes
(the `JsonViewer` on `PipelineStepCard` already renders arbitrary
`input_json`).

### Tests

`tests/test_agent_pipeline.py` (+11): unit tests for each vote extractor
and `_quorum_verdict` (majority-calls-decision, three-way-split-skips,
unanimous-HOLD-is-agreement, insufficient-voters-calls-decision), plus
two full pipeline integration tests satisfying the plan's own acceptance
criteria verbatim — 2/3 agreement asserts the decision LLM `ainvoke` was
awaited; a three-way split asserts it was **not** awaited and the signal
resolves to `HOLD` with `decision_tokens is None`.

### Not verified (needs real trade/pipeline history)

- Real cost reduction from skipped `execution_decision` calls — the test
  suite confirms the call is skipped in the split case, but actual
  `llm_calls` savings need to be measured against live signal volume once
  this runs on a real account (ties into plan 06's cost dashboard).
- Whether `execution_decision` has historically overridden a HOLD
  consensus into a trade (relevant if unanimous-HOLD skipping is revisited
  later) — no historical pipeline data available in this sandbox.
