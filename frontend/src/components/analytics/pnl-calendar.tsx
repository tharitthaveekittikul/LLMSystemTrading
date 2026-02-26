"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CalendarGrid } from "./calendar-grid";
import { analyticsApi } from "@/lib/api/analytics";
import { useTradingStore } from "@/hooks/use-trading-store";
import type { DailyEntry, DailyPnLResponse } from "@/types/trading";

interface PnlCalendarProps {
  selectedDate: string | null;
  onDaySelect: (date: string, entry: DailyEntry) => void;
  onDataChange?: (data: DailyPnLResponse | null, loading: boolean) => void;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function PnlCalendar({ selectedDate, onDaySelect, onDataChange }: PnlCalendarProps) {
  const { activeAccountId } = useTradingStore();
  const now = new Date();
  const [year, setYear] = useState(now.getUTCFullYear());
  const [month, setMonth] = useState(now.getUTCMonth() + 1); // 1-12
  const [data, setData] = useState<DailyPnLResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onDataChangeRef = useRef(onDataChange);
  useEffect(() => {
    onDataChangeRef.current = onDataChange;
  });

  const fetchData = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    setError(null);
    onDataChangeRef.current?.(null, true);
    try {
      const result = await analyticsApi.getDaily({
        year,
        month,
        accountId: activeAccountId,
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
  }, [year, month, activeAccountId]);

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

  return (
    <div>
      {/* Navigation bar */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={prevMonth} aria-label="Previous month">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <h2 className="w-44 text-center text-sm font-semibold">
            {MONTH_NAMES[month - 1]} {year}
          </h2>
          <Button variant="outline" size="icon" onClick={nextMonth} aria-label="Next month">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <Button variant="ghost" size="sm" onClick={goToday}>
          Today
        </Button>
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
      )}
    </div>
  );
}
