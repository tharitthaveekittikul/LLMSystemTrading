"use client";

import { cn } from "@/lib/utils";

interface WeekSummaryCellProps {
  weekNumber: number;
  netPnl: number;
  tradeCount: number;
}

export function WeekSummaryCell({
  weekNumber,
  netPnl,
  tradeCount,
}: WeekSummaryCellProps) {
  const isProfit = netPnl > 0;
  const isLoss = netPnl < 0;

  return (
    <div className="flex min-h-[80px] flex-col items-center justify-center rounded-md border border-dashed border-border bg-muted/5 p-2">
      <p className="text-xs text-muted-foreground">W{weekNumber}</p>
      {tradeCount > 0 ? (
        <>
          <p
            className={cn(
              "text-sm font-semibold",
              isProfit && "text-green-400",
              isLoss && "text-red-400",
              !isProfit && !isLoss && "text-muted-foreground",
            )}
          >
            {netPnl > 0 ? "+" : ""}
            {netPnl.toFixed(2)}
          </p>
          <p className="text-xs text-muted-foreground">{tradeCount}t</p>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">—</p>
      )}
    </div>
  );
}
