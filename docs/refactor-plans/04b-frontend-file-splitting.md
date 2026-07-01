# Plan 4b: Frontend File Splitting

**Branch:** `refactor/split-frontend`
**Depends on:** Plan 1 and Plan 3 merged first (Plan 2 is backend-only,
no dependency needed).
**Risk:** medium — structural change, do one file per commit and run the
done-gate after each.
**Threshold:** any `.tsx`/`.ts` file over ~500 lines (excluding
`types/trading.ts`, which is a type-definition file, not logic — line
count there isn't a "too large" signal the same way it is for a
component).
**Pattern to follow:** the existing `src/components/<feature>/` folders
(e.g. `components/backtest/`, `components/llm-analytics/`,
`components/chart/`, `components/strategies/`). Extract page logic into
matching feature folders — don't invent a new location convention.

## Files in scope (line counts as of this planning pass)

| File | Lines | Notes |
|------|-------|-------|
| `app/strategies/[id]/edit/page.tsx` | 849 | see below — verified structure |
| `app/news/page.tsx` | 803 | |
| `app/backtest/optimize/new/page.tsx` | 765 | |
| `components/ui/sidebar.tsx` | 726 | shadcn/ui primitive — see caveat below |
| `app/strategies/new/page.tsx` | 722 | see below — shares wizard shape with `edit/page.tsx` |
| `app/backtest/optimize/[id]/page.tsx` | 610 | |
| `components/chart/trading-chart.tsx` | 587 | |
| `components/storage/table-browser-sheet.tsx` | 570 | |
| `app/trades/page.tsx` | 554 | |
| `app/strategies/page.tsx` | 540 | |

Re-run the line-count check before starting — Plans 1 and 3 will have
already shrunk some of these.

## `app/strategies/[id]/edit/page.tsx` + `app/strategies/new/page.tsx`
(verified — real duplication opportunity, not just a size problem)

Both pages are the same multi-step wizard (`step` state, `useState` per
field) with only "new vs. existing" differences. `components/strategies/`
already holds some extracted pieces (`strategy-params-form.tsx`,
`strategy-class-selector.tsx`, `skip-hours-grid.tsx`,
`skip-weekdays-grid.tsx`) — the wizard *shell* and *steps* were never
extracted, which is why both pages are still 700+ lines each.

1. Extract each wizard step (basic info, strategy params, risk/schedule
   config, review/submit — confirm exact step boundaries by reading the
   `step === N` conditionals in both files) into
   `components/strategies/steps/step-*.tsx`.
2. Extract the shared form-state logic into a `useStrategyForm()` hook
   (`components/strategies/use-strategy-form.ts`) parameterized by an
   optional `initialStrategy` — `new/page.tsx` calls it with no arg,
   `edit/page.tsx` calls it with the loaded strategy. This removes the
   duplicated `useState` blocks between the two pages, not just their line
   count.
3. Both `page.tsx` files shrink to: fetch/load (edit only) + render
   `<StrategyWizard />` composed of the extracted steps.

## `components/ui/sidebar.tsx` — caveat

If this is a shadcn/ui-generated primitive (check the file header/import
style against other files in `components/ui/`), **do not manually split
it** — shadcn components are meant to be treated as vendored, regenerated
via the CLI rather than hand-refactored, and a manual split will conflict
with future `npx shadcn add` updates. Verify this before touching it; if
it's genuinely hand-written app code, split it like anything else.

## Remaining files (`news/page.tsx`, `optimize/new/page.tsx`,
`optimize/[id]/page.tsx`, `trading-chart.tsx`, `table-browser-sheet.tsx`,
`trades/page.tsx`, `strategies/page.tsx`)

Apply the same process manually at execution time (this plan doc doesn't
pre-read every one of these to keep the doc within budget):

1. Identify the page's distinct visual sections (usually obvious from JSX
   structure — a filter bar, a table, a modal/sheet, a chart panel).
2. Identify state that's local to one section vs. shared across the whole
   page — local state moves with its section into a new component; shared
   state stays in the page (or moves to a hook if the extraction pattern
   from `strategies/` above applies).
3. Extract into `components/<feature>/` following the naming style already
   used there (kebab-case file names, one default export per file).
4. One file split per commit. Run the done-gate after each.

## Acceptance criteria

- No file outside `components/ui/` (vendored primitives) and
  `types/trading.ts` (type-only) exceeds ~500 lines.
- `npm run build` passes after every single file split, not just at the
  end — a broken import in a Next.js page fails the build immediately, so
  this is a cheap, frequent check.
- `npm run lint` passes.
- Manually click through the affected pages in a running `npm run dev`
  session — component extraction is a common source of "looks fine at
  build time, broken prop wiring at runtime" bugs (e.g. a callback prop
  silently becoming `undefined` after extraction).
