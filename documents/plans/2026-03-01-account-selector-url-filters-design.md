# Design: All-Accounts Selector + URL-Based Trade Filters

**Date:** 2026-03-01
**Scope:** `account-selector.tsx`, `use-trading-store.ts`, `app/trades/page.tsx`

---

## 1. AccountSelector — "All Accounts" Option

### Problem
`setActiveAccount` accepts only `number`. There is no way to explicitly reset to "all accounts" — `null` in the store is currently an uninitialized state, not a deliberate selection.

### Solution
- Change `setActiveAccount(id: number)` → `setActiveAccount(id: number | null)` in the store.  `null` = "show all accounts". Backend already handles absent `account_id` as "no filter".
- Add "All accounts" as the first `<SelectItem value="all">` in the selector.
- Map sentinel `"all"` ↔ `null` in the component:
  - `value` prop: `activeAccountId === null ? "all" : activeAccountId.toString()`
  - `onValueChange`: `v === "all" ? setActiveAccount(null) : setActiveAccount(Number(v))`

### Files
- `frontend/src/hooks/use-trading-store.ts` — update `setActiveAccount` signature
- `frontend/src/components/dashboard/account-selector.tsx` — add "All accounts" item + value mapping

---

## 2. Trades Page — URL-Based Filters

### Approach
URL is the single source of truth for page-local filters (`open_only`, `date_from`, `date_to`). No `useState` for those fields — values are read directly from `useSearchParams`. On every filter change, call `router.replace` with updated params, triggering a re-render + re-fetch.

`activeAccountId` remains in Zustand (global app state, not page-local).

### URL Shape
```
/trades?open_only=true&date_from=2024-01-01&date_to=2024-12-31
```

Absent keys mean "not set" (e.g. no date filter).

### Component Split (required for `useSearchParams` in App Router)
`page.tsx` is split into:
1. **`page.tsx`** — thin shell that renders `<Suspense fallback={<LoadingFallback />}><TradesContent /></Suspense>`
2. **`TradesContent`** (same file, not exported) — holds all current logic; reads filters from `useSearchParams`; writes filter changes via `router.replace`

No new files are created.

### Filter Change Pattern
```ts
function updateParams(patch: Record<string, string | undefined>) {
  const next = new URLSearchParams(searchParams.toString());
  for (const [k, v] of Object.entries(patch)) {
    if (v) next.set(k, v); else next.delete(k);
  }
  router.replace(`/trades?${next.toString()}`);
}
```

### Data Loading
`useCallback` load function depends on `[activeAccountId, openOnly, dateFrom, dateTo]` where the latter three are derived from `useSearchParams`. `useEffect(() => { load(); }, [load])` remains unchanged.

### Files
- `frontend/src/app/trades/page.tsx` — refactor in place; add Suspense wrapper + extract `TradesContent`
