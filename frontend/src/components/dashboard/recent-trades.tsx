"use client";

import { useEffect, useState } from "react";
import { tradesApi } from "@/lib/api";
import { formatDateTime } from "@/lib/date";
import type { Trade } from "@/types/trading";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface RecentTradesProps {
  accountId: number | null;
}

export function RecentTrades({ accountId }: RecentTradesProps) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!accountId) {
      setTrades([]);
      return;
    }
    (async () => {
      setLoading(true);
      try {
        const data = await tradesApi.list({ account_id: accountId, limit: 10 });
        setTrades(data.filter((t) => t.closed_at !== null));
      } catch {
        setTrades([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [accountId]);

  const fmt = (v: number | null) =>
    v == null
      ? "—"
      : new Intl.NumberFormat("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(v);

  return (
    <div className="rounded-lg border bg-card flex flex-col h-full">
      <div className="p-3 border-b">
        <h3 className="text-sm font-medium">Recent Closed Trades</h3>
      </div>
      <div className="overflow-auto flex-1">
        {loading ? (
          <p className="text-sm text-muted-foreground p-4">Loading…</p>
        ) : trades.length === 0 ? (
          <p className="text-sm text-muted-foreground p-4">
            No closed trades yet.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="text-xs text-muted-foreground">
                <TableHead>Symbol</TableHead>
                <TableHead>Dir</TableHead>
                <TableHead className="text-right">Profit</TableHead>
                <TableHead className="text-right hidden sm:table-cell">
                  Closed
                </TableHead>
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
                      className={`text-xs font-semibold ${
                        t.direction === "BUY" ? "text-blue-500" : "text-red-500"
                      }`}
                    >
                      {t.direction}
                    </span>
                  </TableCell>
                  <TableCell
                    className={`text-right tabular-nums text-xs ${
                      (t.profit ?? 0) >= 0 ? "text-green-500" : "text-red-500"
                    }`}
                  >
                    {(t.profit ?? 0) >= 0 ? "+" : ""}
                    {fmt(t.profit)}
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground hidden sm:table-cell">
                    {t.closed_at ? formatDateTime(t.closed_at) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
