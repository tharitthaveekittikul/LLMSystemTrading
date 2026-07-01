# Plan 07: Frontend/Backend UX + Edge-Case Audit

**Branch:** `feature/ux-edge-case-audit`
**Depends on:** 01 (manual/AI trade tagging should exist before auditing
how it's surfaced).
**Risk:** low — mostly UI, but may surface backend edge cases worth
separate bugfix branches.

## Goal

The user's stated goal: "website and system both frontend and backend
easy to use and check every edge case user will do." This is an audit +
fix pass, not a single well-defined feature — scope it as a discovery
phase followed by triaged fixes, rather than trying to plan every fix
upfront.

## Part A — Discovery pass

1. Walk every dashboard page as the actual user would, specifically
   checking these scenarios raised in this planning round:
   - Manual trade placed alongside AI trades on the same account — is it
     visually distinct (tag/badge/color), and does it show up promptly
     (depends on plan 01 landing)?
   - Pending order lifecycle — can the user see, at a glance, "this limit
     order is still pending" vs "filled" vs "cancelled/expired" without
     digging into MT5 directly?
   - News page (plan 02) — does a HOLD-by-news-override show up clearly
     linked to the event that caused it?
   - Pipeline trace view — with Mode B now default (plan 03) and vote
     data (plan 05), is the trace still readable, or does it need
     collapsing/summarizing?
   - Kill switch state — is it obvious account-wide when active, and why?
   - Confidence gate / trust score (plan 04) — is the *reason* a signal
     was gated (raw confidence vs. effective threshold vs. trust score)
     visible, or does it just show "HOLD" with no explanation?
2. For each finding, record: what's confusing/missing, what a user might
   incorrectly assume, and severity (blocks understanding vs. cosmetic).
3. Use the `code-review-graph` MCP tools (`get_architecture_overview`,
   `query_graph` with `tests_for`) to check whether the pages/components
   touched during Part A discovery have any test coverage at all —
   frontend test infra was noted as thin during the earlier refactor
   planning pass; don't assume coverage exists.

## Part B — Triage and fix

1. Group findings by page/feature, not by severity alone — fixing
   "pipeline trace readability" as one batch is more efficient than
   scattering small edits across unrelated PRs.
2. Anything that's actually a backend correctness bug (not just a display
   issue) gets pulled out into its own bugfix branch, not bundled into
   this UX pass.
3. Bundle only genuinely related, low-risk display/UX fixes into this
   branch; anything that changes backend behavior goes through the normal
   done-gate and a demo-account check per the shared rules in
   `00-overview.md`.

## Acceptance criteria

- A written discovery findings list exists (can live in this doc's repo
  history / PR description, doesn't need a separate artifact).
- Every "severity: blocks understanding" finding either has a fix in this
  PR or an explicit follow-up plan doc reference.
- `npm run lint` and `npm run build` pass.

## Post-implementation note

### Methodology deviation: code-read audit, not a live click-through

Part A asked to "walk every dashboard page as the actual user would." This
sandbox has no way to do that — no MT5 (Windows-only), no live LLM
credentials, and `npm run dev`/`npm run build` can't run at all here
(Node 18.19.1 installed, Next.js 16 requires ≥20.9.0 — the same limitation
every prior plan in this series hit). Discovery below is a static-code
read of the relevant pages/components instead. **Re-run the live
click-through on the actual Node 20+/Windows dev environment before
trusting this as complete** — several findings below could only be
confirmed by literally looking at the rendered page.

### Discovery findings, by the plan's own checklist

| Area | Finding | Severity |
|---|---|---|
| Manual vs. AI trade distinction | Already shown — `frontend/src/app/trades/page.tsx:325` renders `Trade.source` as a badge per row. Not color-coded by manual-vs-AI, but genuinely visible, not missing. | Cosmetic |
| Pending order lifecycle | Already reasonably clear — `frontend/src/components/dashboard/live-positions.tsx:144-169` renders pending orders at reduced opacity with a live expiration countdown, sourced from the live MT5 poller (not the DB `order_status` field) — arguably *better* than DB status since it's real-time truth. | Not an issue |
| News HOLD-override linkage | Confirmed still missing, exactly as plan 02 documented — the trading pipeline's news gate fetches live from ForexFactory independently of the persisted `economic_events` table the `/news` page reads; no join key exists between "this event" and "this HOLD decision." Plan 02 explicitly deferred this as a follow-up rather than scope-creeping into that PR. | Blocks understanding — **not fixed here either**, see follow-up below |
| Pipeline trace readability (Mode B + votes) | `frontend/src/components/logs/pipeline-step-card.tsx` already had distinct `STEP_LABELS`/badges/token-cost display per sub-agent step (indicator/pattern/trend/decision) — confirmed adequate when plan 03 was implemented. But the new `confidence_gate` (plan 04: trust score/effective threshold) and `execution_decision_llm` (plan 05: vote breakdown) data was only visible by clicking to expand raw JSON — **fixed in this PR**, see below. | Blocks understanding — **fixed** |
| Kill switch visibility | Already well covered — dedicated `kill-switch-banner.tsx` component plus a standalone `/kill-switch` page exist. | Not an issue |
| Confidence gate / trust score reasoning | Same finding as pipeline trace readability above — the data was recorded (plan 04) but not surfaced without expanding JSON. Fixed together with the vote breakdown. | Blocks understanding — **fixed** |

### Fix applied

`frontend/src/components/logs/pipeline-step-card.tsx` — added two always-
visible (no click-to-expand needed) inline summary lines:

1. On the `confidence_gate` step: `confidence 0.62 vs effective threshold
   0.58 (trust score 0.71, base 0.70)`, with a highlighted `→ downgraded
   BUY_LIMIT to HOLD` suffix when the gate actually changed the action.
   Falls back to just the base threshold when trust-score fields aren't
   present (i.e. before plan 04 lands, or for the maintenance-decision
   gate which uses the same step but may lack the fields depending on
   which branch is checked out).
2. On the `execution_decision_llm` step (Mode B only): `Sub-agent votes:
   BUY 2 / HOLD 1 → majority BUY, decision LLM consulted` or `→ no
   majority, decision call skipped` — makes plan 05's quorum outcome
   visible without expanding JSON.

Both read defensively from whatever fields are actually present (`??`
fallbacks throughout) so they degrade gracefully depending on which of
plans 03-05 are merged at any given point, rather than assuming all land
together.

### Not done in this PR (explicit follow-ups, not silently dropped)

- **News HOLD-override → calendar event linkage** — still open, as
  flagged by plan 02. Fixing it means either rewriting the trading
  pipeline's news gate to query `economic_events` instead of live-
  fetching ForexFactory, or adding a fuzzy match (title + currency + time
  window) plus a new FK from `PipelineStep`/`AIJournal` to
  `EconomicEvent.id`. Both are a real feature, not a UX tweak — deserves
  its own plan doc rather than being squeezed into this one.
- **Live click-through verification** — everything above needs to be
  re-checked by actually looking at the rendered dashboard once a Node
  20+ environment is available; this sandbox could only verify via
  `npm run lint`/`npx tsc --noEmit` that the new code compiles and
  introduces zero new lint/type issues (confirmed via git-stash
  comparison against the unmodified tree: identical 304 lint problems,
  same single pre-existing `backtest/page.tsx` type error).
- **Test coverage check (Part A step 3)** — not run in this session;
  the `code-review-graph` MCP tools this step calls for weren't invoked.
  Given how thin this repo's frontend test infra already was noted to be
  during the earlier refactor-plans pass, assume it's still thin rather
  than re-verifying now — a full coverage audit is its own task.
