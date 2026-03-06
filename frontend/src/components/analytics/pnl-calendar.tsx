"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { CalendarGrid } from "./calendar-grid";
import { analyticsApi } from "@/lib/api/analytics";
import { accountsApi } from "@/lib/api/accounts";
import { useTradingStore } from "@/hooks/use-trading-store";
import type { DailyEntry, DailyPnLResponse } from "@/types/trading";

interface PnlCalendarProps {
  selectedDate: string | null;
  onDaySelect: (date: string, entry: DailyEntry) => void;
  onDataChange?: (data: DailyPnLResponse | null, loading: boolean) => void;
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

type AccountTypeFilter = "all" | "live" | "demo";

const ACCOUNT_TYPE_FILTERS: { label: string; value: AccountTypeFilter }[] = [
  { label: "All", value: "all" },
  { label: "Live", value: "live" },
  { label: "Demo", value: "demo" },
];

export function PnlCalendar({
  selectedDate,
  onDaySelect,
  onDataChange,
}: PnlCalendarProps) {
  const { activeAccountId } = useTradingStore();
  const now = new Date();
  const [year, setYear] = useState(now.getUTCFullYear());
  const [month, setMonth] = useState(now.getUTCMonth() + 1); // 1-12
  const [data, setData] = useState<DailyPnLResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountTypeFilter, setAccountTypeFilter] =
    useState<AccountTypeFilter>("all");

  // Reset filter when user selects a specific account (filter doesn't apply there)
  useEffect(() => {
    if (activeAccountId !== null) {
      setAccountTypeFilter("all");
    }
  }, [activeAccountId]);

  const onDataChangeRef = useRef(onDataChange);
  useEffect(() => {
    onDataChangeRef.current = onDataChange;
  });

  const isLiveParam =
    activeAccountId !== null
      ? undefined
      : accountTypeFilter === "live"
        ? true
        : accountTypeFilter === "demo"
          ? false
          : undefined;

  const fetchData = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true);
      setError(null);
      onDataChangeRef.current?.(null, true);
      try {
        const result = await analyticsApi.getDaily({
          year,
          month,
          accountId: activeAccountId,
          isLive: isLiveParam,
          signal,
        });
        if (signal.aborted) return;
        setData(result);
        onDataChangeRef.current?.(result, false);
      } catch (e) {
        if (signal.aborted) return;
        const msg = e instanceof Error ? e.message : "Failed to load data";
        setError(msg);
        onDataChangeRef.current?.(null, false);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [year, month, activeAccountId, isLiveParam],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, [fetchData]);

  function prevMonth() {
    if (month === 1) {
      setYear((y) => y - 1);
      setMonth(12);
    } else {
      setMonth((m) => m - 1);
    }
  }

  function nextMonth() {
    if (month === 12) {
      setYear((y) => y + 1);
      setMonth(1);
    } else {
      setMonth((m) => m + 1);
    }
  }

  function goToday() {
    const n = new Date();
    setYear(n.getUTCFullYear());
    setMonth(n.getUTCMonth() + 1);
  }

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      // Always sync ALL accounts so analytics data is complete regardless of the
      // display filter (activeAccountId only controls which account to show, not sync).
      const r = await accountsApi.syncAll(90);
      if (r.errors.length > 0) {
        toast.warning(`Sync partial: ${r.errors.length} account(s) failed`);
      }
      const parts: string[] = [];
      if (r.imported > 0) parts.push(`${r.imported} new`);
      if (r.updated > 0) parts.push(`${r.updated} closed`);
      const summary = parts.length > 0 ? parts.join(", ") : "0 new";
      toast.success(`Synced: ${summary} trade${r.imported + r.updated !== 1 ? "s" : ""} from ${r.accounts_synced} account${r.accounts_synced !== 1 ? "s" : ""}`);
      // Re-fetch calendar data with fresh DB content
      const controller = new AbortController();
      await fetchData(controller.signal);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "MT5 sync failed — is the terminal running?");
    } finally {
      setSyncing(false);
    }
  }, [fetchData]);

  return (
    <div>
      {/* Navigation bar */}
      <div className="mb-4 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={prevMonth}
            aria-label="Previous month"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <h2 className="w-44 text-center text-sm font-semibold">
            {MONTH_NAMES[month - 1]} {year}
          </h2>
          <Button
            variant="outline"
            size="icon"
            onClick={nextMonth}
            aria-label="Next month"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          {/* Demo / Live filter — only when "All accounts" is selected */}
          {activeAccountId === null && (
            <div className="flex rounded-md border overflow-hidden text-xs">
              {ACCOUNT_TYPE_FILTERS.map(({ label, value }) => (
                <button
                  key={value}
                  onClick={() => setAccountTypeFilter(value)}
                  className={[
                    "px-3 py-1 transition-colors",
                    accountTypeFilter === value
                      ? "bg-primary text-primary-foreground font-semibold"
                      : "bg-background text-muted-foreground hover:bg-muted",
                    // dividers between buttons
                    value !== "all" ? "border-l" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          <Button variant="ghost" size="sm" onClick={goToday}>
            Today
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleSync}
            disabled={syncing || loading}
          >
            <RefreshCw className={`mr-2 h-3.5 w-3.5${syncing ? " animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync MT5"}
          </Button>
        </div>
      </div>

      {/* States */}
      {loading && (
        <p className="py-8 text-center text-sm text-muted-foreground animate-pulse">
          Loading…
        </p>
      )}

      {!loading && error && (
        <p className="py-8 text-center text-sm text-red-400">{error}</p>
      )}

      {!loading && !error && (
        <>
          {data !== null && data.days.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No closed trades in {MONTH_NAMES[month - 1]} {year}.
            </p>
          )}
          <CalendarGrid
            year={year}
            month={month}
            days={data?.days ?? []}
            selectedDate={selectedDate}
            onDaySelect={(date) => {
              const entry = data?.days.find((d) => d.date === date);
              if (entry) onDaySelect(date, entry);
            }}
          />
        </>
      )}
    </div>
  );
}
