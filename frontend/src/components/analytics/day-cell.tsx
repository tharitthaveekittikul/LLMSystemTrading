"use client";

import { cn } from "@/lib/utils";
import type { DailyEntry } from "@/types/trading";

interface DayCellProps {
  day: number; // 1-31 for real days, 0 for padding cells
  entry?: DailyEntry;
  isCurrentMonth: boolean;
  isSelected: boolean;
  isToday: boolean;
  onClick?: () => void;
}

export function DayCell({
  day,
  entry,
  isCurrentMonth,
  isSelected,
  isToday,
  onClick,
}: DayCellProps) {
  if (day === 0) {
    return <div className="min-h-[80px] rounded-md bg-muted/10 opacity-20" />;
  }

  const hasTrades = !!entry;
  const pnl = entry?.net_pnl ?? 0;
  const isProfit = hasTrades && pnl > 0;
  const isLoss = hasTrades && pnl < 0;

  return (
    <div
      onClick={hasTrades && isCurrentMonth ? onClick : undefined}
      className={cn(
        "min-h-[80px] rounded-md border p-2 transition-colors",
        isCurrentMonth ? "opacity-100" : "opacity-30",
        hasTrades && isProfit && "border-green-700/50 bg-green-700/10",
        hasTrades && isLoss && "border-red-700/50 bg-red-700/10",
        !hasTrades && "border-border bg-muted/10",
        hasTrades && isCurrentMonth && "cursor-pointer hover:opacity-80",
        isSelected && "ring-2 ring-blue-500",
        isToday && !isSelected && "ring-2 ring-primary",
      )}
    >
      <div className="flex items-start justify-between">
        <span className={cn("text-sm font-medium", isToday && "text-primary")}>
          {day}
        </span>
      </div>
      {hasTrades && isCurrentMonth && (
        <div className="mt-1">
          <p
            className={cn(
              "text-sm font-semibold",
              isProfit && "text-green-600",
              isLoss && "text-red-400",
            )}
          >
            {pnl > 0 ? "+" : ""}
            {pnl.toFixed(2)}
          </p>
          <p className="text-xs text-muted-foreground">
            {entry!.trade_count} trade{entry!.trade_count !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
