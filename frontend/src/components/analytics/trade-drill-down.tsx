"use client";

import { useState, useEffect } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api";
import { useTradingStore } from "@/hooks/use-trading-store";
import type { Trade, DailyEntry } from "@/types/trading";

interface TradeDrillDownProps {
  date: string | null; // "YYYY-MM-DD"
  entry: DailyEntry | null;
  open: boolean;
  onClose: () => void;
}

function formatDuration(openTime: string, closeTime: string | null): string {
  if (!closeTime) return "—";
  const ms = new Date(closeTime).getTime() - new Date(openTime).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

export function TradeDrillDown({
  date,
  entry,
  open,
  onClose,
}: TradeDrillDownProps) {
  const { activeAccountId } = useTradingStore();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !date) return;
    const controller = new AbortController();
    (async () => {
      setLoading(true);
      const q = new URLSearchParams({ date_from: date, date_to: date });
      if (activeAccountId != null) q.set("account_id", String(activeAccountId));
      try {
        const data = await apiRequest<Trade[]>(`/trades?${q}`, {
          signal: controller.signal,
        });
        setTrades(data);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        console.error("[TradeDrillDown] Failed to load trades:", err);
        setTrades([]);
      } finally {
        setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [open, date, activeAccountId]);

  const pnl = entry?.net_pnl ?? 0;
  const isProfit = pnl > 0;
  const isLoss = pnl < 0;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-[620px] sm:max-w-[620px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-3">
            <span>{date ?? "—"}</span>
            {entry && (
              <span
                className={cn(
                  "text-base font-semibold",
                  isProfit
                    ? "text-green-400"
                    : isLoss
                      ? "text-red-400"
                      : "text-muted-foreground",
                )}
              >
                {pnl > 0 ? "+" : ""}
                {pnl.toFixed(2)}
              </span>
            )}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-4">
          {loading ? (
            <p className="text-sm text-muted-foreground animate-pulse">
              Loading trades…
            </p>
          ) : trades.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No trades found for this day.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Dir</TableHead>
                  <TableHead>Vol</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead>PnL</TableHead>
                  <TableHead>Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-mono text-xs">
                      {t.symbol}
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "text-xs font-semibold uppercase",
                          t.direction === "BUY"
                            ? "text-green-400"
                            : "text-red-400",
                        )}
                      >
                        {t.direction}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">{t.volume}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {t.entry_price}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {t.close_price ?? "—"}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-xs font-semibold",
                        (t.profit ?? 0) > 0
                          ? "text-green-400"
                          : (t.profit ?? 0) < 0
                            ? "text-red-400"
                            : "text-muted-foreground",
                      )}
                    >
                      {t.profit != null
                        ? `${t.profit > 0 ? "+" : ""}${t.profit.toFixed(2)}`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {formatDuration(t.opened_at, t.closed_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
