"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { BacktestTrade } from "@/types/trading";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
      <div className="rounded-md border">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
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
                <TableHead
                  key={h}
                  className="text-xs font-medium text-muted-foreground whitespace-nowrap"
                >
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {slice.map((t, i) => (
              <TableRow key={t.id} className={cn(i % 2 !== 0 && "bg-muted/20")}>
                <TableCell className="text-xs text-muted-foreground">
                  {page * PAGE_SIZE + i + 1}
                </TableCell>
                <TableCell
                  className={cn(
                    "text-xs font-bold",
                    t.direction === "BUY" ? "text-green-600" : "text-red-500",
                  )}
                >
                  {t.direction}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {t.entry_time.slice(0, 16)}
                </TableCell>
                <TableCell className="text-xs tabular-nums">
                  {t.entry_price.toFixed(5)}
                </TableCell>
                <TableCell className="text-xs tabular-nums">
                  {t.exit_price?.toFixed(5) ?? "—"}
                </TableCell>
                <TableCell className="text-xs tabular-nums text-red-500">
                  {t.stop_loss.toFixed(5)}
                </TableCell>
                <TableCell className="text-xs tabular-nums text-green-600">
                  {t.take_profit.toFixed(5)}
                </TableCell>
                <TableCell
                  className={cn(
                    "text-xs font-medium tabular-nums",
                    (t.profit ?? 0) >= 0 ? "text-green-600" : "text-red-500",
                  )}
                >
                  {t.profit != null
                    ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}`
                    : "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground capitalize">
                  {t.exit_reason ?? "open"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
