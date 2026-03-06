"use client";

import { DayCell } from "./day-cell";
import { WeekSummaryCell } from "./week-summary-cell";
import type { DailyEntry } from "@/types/trading";

interface CalendarGridProps {
  year: number;
  month: number; // 1-12
  days: DailyEntry[];
  selectedDate: string | null;
  onDaySelect: (date: string) => void;
}

const DAY_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function CalendarGrid({
  year,
  month,
  days,
  selectedDate,
  onDaySelect,
}: CalendarGridProps) {
  // Build lookup map: "YYYY-MM-DD" -> DailyEntry
  const dayMap = new Map(days.map((d) => [d.date, d]));

  const now = new Date();
  const todayStr = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-${String(now.getUTCDate()).padStart(2, "0")}`;

  // First weekday of month (0=Sun) and total days in month
  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();

  // Flat array: 0 = padding cell, 1-31 = real day
  const cells: number[] = [
    ...Array(firstDay).fill(0),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  // Pad end to complete last week
  while (cells.length % 7 !== 0) cells.push(0);

  // Split into rows of 7
  const weeks: number[][] = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }

  function pad(n: number) {
    return String(n).padStart(2, "0");
  }

  return (
    <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <div className="min-w-[480px]">
        {/* Column headers */}
        <div className="mb-1 grid grid-cols-[repeat(7,1fr)_72px] gap-1 sm:grid-cols-[repeat(7,1fr)_100px]">
          {DAY_HEADERS.map((h) => (
            <div
              key={h}
              className="py-1 text-center text-xs font-medium text-muted-foreground"
            >
              {h}
            </div>
          ))}
          <div className="py-1 text-center text-xs font-medium text-muted-foreground">
            Week
          </div>
        </div>

        {/* Week rows */}
        {weeks.map((week, wi) => {
          const weekEntries = week
            .filter((d) => d > 0)
            .map((d) => dayMap.get(`${year}-${pad(month)}-${pad(d)}`))
            .filter((e): e is DailyEntry => e !== undefined);

          const weekPnl = Math.round(
            weekEntries.reduce((sum, e) => sum + e.net_pnl, 0) * 100,
          ) / 100;
          const weekTrades = weekEntries.reduce((sum, e) => sum + e.trade_count, 0);

          return (
            <div
              key={wi}
              className="mb-1 grid grid-cols-[repeat(7,1fr)_72px] gap-1 sm:grid-cols-[repeat(7,1fr)_100px]"
            >
              {week.map((day, di) => {
                const dateStr =
                  day > 0 ? `${year}-${pad(month)}-${pad(day)}` : "";
                return (
                  <DayCell
                    key={di}
                    day={day}
                    entry={day > 0 ? dayMap.get(dateStr) : undefined}
                    isCurrentMonth={day > 0}
                    isSelected={dateStr === selectedDate}
                    isToday={dateStr === todayStr}
                    onClick={day > 0 ? () => onDaySelect(dateStr) : undefined}
                  />
                );
              })}
              <WeekSummaryCell
                weekNumber={wi + 1}
                netPnl={weekPnl}
                tradeCount={weekTrades}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
