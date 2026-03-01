"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { BacktestTrade } from "@/types/trading";

interface Props {
  trades: BacktestTrade[];
}

const PAGE_SIZE = 50;

export function BacktestTradeTable({ trades }: Props) {
  const [page, setPage] = useState(0);

  if (trades.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-4">
        No trades
      </p>
    );
  }

  const totalPages = Math.ceil(trades.length / PAGE_SIZE);
  const slice = trades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50">
            <tr>
              {[
                "#",
                "Dir",
                "Entry Time",
                "Entry",
                "Exit",
                "SL",
                "TP",
                "P&L",
                "Exit Reason",
              ].map((h) => (
                <th
                  key={h}
                  className="px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((t, i) => (
              <tr
                key={t.id}
                className={cn("border-t", i % 2 !== 0 && "bg-muted/20")}
              >
                <td className="px-2 py-1 text-muted-foreground">
                  {page * PAGE_SIZE + i + 1}
                </td>
                <td
                  className={cn(
                    "px-2 py-1 font-bold",
                    t.direction === "BUY" ? "text-green-600" : "text-red-500",
                  )}
                >
                  {t.direction}
                </td>
                <td className="px-2 py-1 text-muted-foreground whitespace-nowrap">
                  {t.entry_time.slice(0, 16)}
                </td>
                <td className="px-2 py-1 tabular-nums">
                  {t.entry_price.toFixed(5)}
                </td>
                <td className="px-2 py-1 tabular-nums">
                  {t.exit_price?.toFixed(5) ?? "—"}
                </td>
                <td className="px-2 py-1 tabular-nums text-red-500">
                  {t.stop_loss.toFixed(5)}
                </td>
                <td className="px-2 py-1 tabular-nums text-green-600">
                  {t.take_profit.toFixed(5)}
                </td>
                <td
                  className={cn(
                    "px-2 py-1 font-medium tabular-nums",
                    (t.profit ?? 0) >= 0 ? "text-green-600" : "text-red-500",
                  )}
                >
                  {t.profit != null
                    ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}`
                    : "—"}
                </td>
                <td className="px-2 py-1 text-muted-foreground capitalize">
                  {t.exit_reason ?? "open"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{trades.length} total trades</span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              ←
            </Button>
            <span className="px-2">
              {page + 1} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
            >
              →
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
