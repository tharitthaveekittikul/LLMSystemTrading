# Account Selector + URL Filters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add "All accounts" option to the account selector and replace local useState filters in the trades page with URL search params.

**Architecture:** Three targeted edits — store type loosened to accept `null`, selector gains an "All accounts" item, trades page splits into a `<Suspense>` shell + inner `TradesContent` that reads/writes `useSearchParams`.

**Tech Stack:** Next.js 16 App Router, TypeScript, Zustand, shadcn/ui Select

---

### Task 1: Loosen `setActiveAccount` to accept `null`

**Files:**
- Modify: `frontend/src/hooks/use-trading-store.ts`

**Step 1: Update the interface**

In `TradingState`, change:
```ts
setActiveAccount: (accountId: number) => void;
```
to:
```ts
setActiveAccount: (accountId: number | null) => void;
```

**Step 2: Update the implementation**

The implementation body `(accountId) => set({ activeAccountId: accountId })` requires no change — the type widening is sufficient.

**Step 3: Verify TypeScript compiles**

Run from `/frontend`:
```bash
npx tsc --noEmit
```
Expected: no errors.

---

### Task 2: Add "All accounts" option to AccountSelector

**Files:**
- Modify: `frontend/src/components/dashboard/account-selector.tsx`

**Step 1: Replace the `<Select>` value + handler**

Change:
```tsx
value={activeAccountId?.toString() ?? ""}
onValueChange={(v) => setActiveAccount(Number(v))}
```
to:
```tsx
value={activeAccountId?.toString() ?? "all"}
onValueChange={(v) => setActiveAccount(v === "all" ? null : Number(v))}
```

**Step 2: Add "All accounts" as first SelectItem**

Inside `<SelectContent>`, before the `accounts.map(...)`, add:
```tsx
<SelectItem value="all">All accounts</SelectItem>
```

**Step 3: Verify TypeScript compiles**

```bash
npx tsc --noEmit
```
Expected: no errors.

**Step 4: Manual smoke test**

Open the dashboard. Confirm:
- Dropdown shows "All accounts" as first option
- Selecting an account works as before
- Selecting "All accounts" resets the selector label to "All accounts"

---

### Task 3: Refactor TradesPage to URL-based filters

**Files:**
- Modify: `frontend/src/app/trades/page.tsx`

**Step 1: Add new imports at the top**

Replace:
```tsx
import { useCallback, useEffect, useState } from "react";
```
with:
```tsx
import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
```

**Step 2: Extract `TradesContent` — move all current logic into it**

Rename the current `export default function TradesPage()` to `function TradesContent()` (not exported).

**Step 3: Replace local filter state with `useSearchParams`**

Inside `TradesContent`, remove:
```tsx
const [openOnly, setOpenOnly] = useState(false);
const [dateFrom, setDateFrom] = useState("");
const [dateTo, setDateTo] = useState("");
```

Replace with:
```tsx
const router = useRouter();
const searchParams = useSearchParams();

const openOnly = searchParams.get("open_only") === "true";
const dateFrom = searchParams.get("date_from") ?? "";
const dateTo = searchParams.get("date_to") ?? "";
```

**Step 4: Add `updateParams` helper**

Add this function inside `TradesContent`, before the `load` callback:
```tsx
function updateParams(patch: Record<string, string | undefined>) {
  const next = new URLSearchParams(searchParams.toString());
  for (const [k, v] of Object.entries(patch)) {
    if (v) next.set(k, v);
    else next.delete(k);
  }
  router.replace(`/trades?${next.toString()}`);
}
```

**Step 5: Update filter onChange handlers**

Replace the checkbox `onChange`:
```tsx
onChange={(e) => setOpenOnly(e.target.checked)}
```
with:
```tsx
onChange={(e) =>
  updateParams({ open_only: e.target.checked ? "true" : undefined })
}
```

Replace the "From" date `onChange`:
```tsx
onChange={(e) => setDateFrom(e.target.value)}
```
with:
```tsx
onChange={(e) => updateParams({ date_from: e.target.value || undefined })}
```

Replace the "To" date `onChange`:
```tsx
onChange={(e) => setDateTo(e.target.value)}
```
with:
```tsx
onChange={(e) => updateParams({ date_to: e.target.value || undefined })}
```

**Step 6: Update the "no account" hint**

The old hint said "Select an account in the sidebar to filter". Since `null` now means "All accounts" (deliberate), change it to:
```tsx
{activeAccountId == null && (
  <span className="text-xs text-muted-foreground">Showing all accounts</span>
)}
```

**Step 7: Add `LoadingFallback` and new `TradesPage` export**

After `TradesContent`, add:
```tsx
function LoadingFallback() {
  return (
    <SidebarInset>
      <AppHeader title="Trades" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    </SidebarInset>
  );
}

export default function TradesPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <TradesContent />
    </Suspense>
  );
}
```

**Step 8: Verify TypeScript compiles**

```bash
npx tsc --noEmit
```
Expected: no errors.

**Step 9: Manual smoke test**

1. Navigate to `/trades` — page loads, no filters active
2. Check "Open only" → URL becomes `/trades?open_only=true`, table refreshes
3. Uncheck → URL returns to `/trades`, table refreshes
4. Set a date range → URL shows `date_from=...&date_to=...`
5. Copy the URL, open in a new tab → filters are pre-applied
6. Use browser back → filters revert correctly
