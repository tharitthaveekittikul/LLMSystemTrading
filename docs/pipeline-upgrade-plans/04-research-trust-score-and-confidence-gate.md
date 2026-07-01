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
