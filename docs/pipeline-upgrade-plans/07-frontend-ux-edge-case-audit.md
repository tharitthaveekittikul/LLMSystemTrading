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
