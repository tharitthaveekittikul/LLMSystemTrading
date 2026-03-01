"use client";

import { useEffect, useState } from "react";
import { tradesApi } from "@/lib/api";
import { formatDateTime } from "@/lib/date";
import type { Trade } from "@/types/trading";

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
    setLoading(true);
    tradesApi
      .list({ account_id: accountId, limit: 10 })
      .then((data) => setTrades(data.filter((t) => t.closed_at !== null)))
      .catch(() => setTrades([]))
      .finally(() => setLoading(false));
  }, [accountId]);

  const fmt = (v: number | null) =>
    v == null
      ? "—"
      : new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);

  return (
    <div className="rounded-lg border bg-card flex flex-col h-full">
      <div className="p-3 border-b">
        <h3 className="text-sm font-medium">Recent Closed Trades</h3>
      </div>
      <div className="overflow-auto flex-1">
        {loading ? (
          <p className="text-sm text-muted-foreground p-4">Loading…</p>
        ) : trades.length === 0 ? (
          <p className="text-sm text-muted-foreground p-4">No closed trades yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="text-left p-2">Symbol</th>
                <th className="text-left p-2">Dir</th>
                <th className="text-right p-2">Profit</th>
                <th className="text-right p-2 hidden sm:table-cell">Closed</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b last:border-0">
                  <td className="p-2 font-mono text-xs">{t.symbol}</td>
                  <td className="p-2">
                    <span
                      className={`text-xs font-semibold ${
                        t.direction === "BUY" ? "text-blue-500" : "text-red-500"
                      }`}
                    >
                      {t.direction}
                    </span>
                  </td>
                  <td
                    className={`p-2 text-right tabular-nums text-xs ${
                      (t.profit ?? 0) >= 0 ? "text-green-500" : "text-red-500"
                    }`}
                  >
                    {(t.profit ?? 0) >= 0 ? "+" : ""}
                    {fmt(t.profit)}
                  </td>
                  <td className="p-2 text-right text-xs text-muted-foreground hidden sm:table-cell">
                    {t.closed_at ? formatDateTime(t.closed_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
