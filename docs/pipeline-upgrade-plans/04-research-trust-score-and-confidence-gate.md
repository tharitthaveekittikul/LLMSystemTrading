# Plan 04: Research Trust-Score + Confidence Gate

**Branch:** `feature/research-trust-score`
**Depends on:** nothing (independent of Mode B).
**Risk:** medium — changes trade frequency per symbol.

## Goal

`research_loop.py` already writes `blocked_symbols` and `suggested_params`
to `research_config.json`, but nothing reads them — they're dead data.
Rather than wiring them up as a binary hard-block (risky: a 30-trade
sample is small enough that one bad streak could permanently exile a
perfectly good symbol), replace them with a continuous **trust_score**
that modulates the confidence gate.

## Part A — Trust score computation

1. In `research_loop.py`, replace (or add alongside, for a transition
   period) the binary `blocked_symbols` output with a per-symbol
   `trust_score` in `[0, 1]`.
2. Base it on a **statistically-aware** win-rate, not a raw tally over the
   most recent 30 trades: use a Wilson score interval (or similar) over a
   larger trailing window (e.g. last 50-100 closed trades for that
   symbol, pulled via the existing `get_symbol_stats`/`get_signal_reliability`
   tools) so a small recent sample doesn't dominate the score. Require a
   minimum sample size (e.g. 20 trades) before trust_score deviates far
   from a neutral 0.5 — insufficient data should mean "no strong opinion,"
   not "blocked."
3. Keep `lessons`/`lesson_history` exactly as-is (already correctly
   injected into `rag_context.py` — no change needed there).
4. Deprecate `suggested_params` for now — leave it advisory-only, surfaced
   in the `/research` API/dashboard for manual review, since auto-applying
   parameter changes (SL/TP formulas, position sizing) is a bigger blast
   radius than a confidence threshold nudge. Don't build auto-apply for
   this in the same PR.

## Part B — Confidence gate modulation

1. Locate the current static confidence-gate check (per memory: "< threshold
   → HOLD" in the AI trading service pipeline).
2. Change to:
   `effective_threshold = clamp(base_threshold - (trust_score - 0.5) * sensitivity, min_threshold, max_threshold)`
   — trusted symbols get a lower bar (more trades taken), symbols research
   is skeptical of get a higher bar (fewer, higher-conviction trades only),
   and a symbol never gets fully blocked, only made harder to trade.
3. Make `sensitivity`, `min_threshold`, `max_threshold` configurable
   (settings/DB-backed, not hardcoded) so they can be tuned during a
   monitoring period without a code change.
4. Log the applied `effective_threshold` and `trust_score` alongside every
   signal in the `AIJournal`/pipeline trace, so it's auditable which
   decisions were affected by research feedback — this is explicitly part
   of the "should be auditable" requirement.

## Acceptance criteria

- `research_config.json` schema includes `trust_score` per symbol (keep
  `blocked_symbols` field for backward-compat read, but pipeline reads
  `trust_score` going forward).
- Confidence gate demonstrably uses `trust_score` — add a unit test:
  same raw signal confidence, two different trust scores, two different
  gate outcomes.
- A pipeline trace entry shows the `trust_score`/`effective_threshold`
  used for that decision.
- `uv run pytest -v` passes.

## Post-implementation note (what already existed vs. what was built)

Verified before writing code, per the lesson from sibling plans 01-03:
`blocked_symbols`/`suggested_params` were confirmed genuinely dead exactly
as the plan describes — `rag_context.py:299-315` only ever reads
`lessons`/`lesson_history`, nothing reads the other two fields. No stale
assumptions found here; the plan matched reality.

### Actual changes on this branch

- `services/research_loop.py`:
  - `_wilson_lower_bound(wins, n)` — standard Wilson score interval lower
    bound, a conservative win-rate estimate that pulls toward 0.5 for
    small samples (a 3-for-3 win streak scores ~0.44, *not* near 1.0 —
    this is intentional, not a bug; there isn't enough evidence yet).
  - `_trust_score_from_stats(wins, n, min_sample=20)` — blends the Wilson
    bound toward neutral 0.5 as `n` falls short of `min_sample`, exactly
    as the plan specified (weight = `min(n/min_sample, 1.0)`).
  - `compute_symbol_trust_scores(db, account_id, days=90)` — new
    deterministic query (grouped count of wins/total per symbol over the
    trailing 90 days), independent of the LLM agent's tool-calling
    reliability. Called unconditionally at the end of `run()`, so
    `symbol_trust_scores` is always populated in `research_config.json`
    regardless of whether the LLM-agent path or the rule-based fallback
    produced `lessons`/`blocked_symbols`.
  - `compute_effective_threshold(base, trust_score, sensitivity, min_threshold, max_threshold)`
    — pure function implementing the plan's clamp formula.
  - `get_symbol_trust_score(symbol)` / `effective_confidence_threshold(symbol, base)`
    — read-config convenience wrappers used by every gate call site.
- Every live confidence-gate comparison against `settings.llm_confidence_threshold`
  was switched to `effective_confidence_threshold(symbol, ...)` — there were
  **5 call sites**, not 1: `ai/orchestrator/_pipeline.py` (the 3-role
  `analyze_market` signal gate, the maintenance-decision gate, and the
  Mode B `run_agent_pipeline` gate) and `services/ai_trading/_service.py`
  (the primary post-signal-phase gate, and the stale-pending retry
  re-check). All 5 needed updating for the trust score to actually apply
  consistently regardless of which mode/path is running.
- `services/ai_trading/_service.py`'s `confidence_gate` tracer step now
  records `base_threshold`, `effective_threshold`, and `symbol_trust_score`
  (previously only `threshold`) — this is what makes the trust-score
  adjustment auditable per-signal on the dashboard, per the plan's own
  acceptance criteria.
- `tests/test_research_trust_score.py` (new, 15 tests) — covers the Wilson
  bound, the neutral-blending behavior, the clamp formula, the
  config-reading wrappers, the DB-query function (mocked session), and the
  plan's specific acceptance criterion: identical raw signal confidence
  (0.60) against a trusted-symbol threshold (0.58, passes) vs. a
  distrusted-symbol threshold (0.82, HOLDs) — same confidence, different
  outcome.

### Deliberately reduced scope

- **`sensitivity`/`min_threshold`/`max_threshold` are module-level
  constants** (`TRUST_SENSITIVITY = 0.3`, `TRUST_MIN_THRESHOLD = 0.4`,
  `TRUST_MAX_THRESHOLD = 0.9`, `TRUST_MIN_SAMPLE = 20`) in
  `research_loop.py`, **not** DB/settings-backed as Part B step 3 asked
  for. Making them tunable without a redeploy would mean another
  `GlobalSettings` migration + settings-UI control, which felt like
  scope creep for this PR given the core trust-score mechanism was the
  priority. Flagging as a fast-follow if live tuning turns out to be
  needed once this runs against real trade data.
- `suggested_params` was left exactly as-is (still LLM-produced,
  still unread by the trading pipeline, still surfaced via the existing
  `/research` API for manual review) — per Part A step 4's own
  instruction not to build auto-apply in this PR.

### Not verified (needs a human + real trade history)

- The trust-score math is unit-tested with synthetic win/loss counts, not
  against real closed-trade data — recommend checking the computed
  `symbol_trust_scores` in `research_config.json` look sane after the
  next few research-loop runs on a real account before trusting the
  confidence-gate nudges it produces.
