"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { accountsApi } from "@/lib/api/accounts";
import { formatDateTime } from "@/lib/date";
import type { HistoryDeal } from "@/types/trading";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Props {
  accountId: number;
}

// ── Derived type: one row per closed position ─────────────────────────────────

interface PairedTrade {
  position_id: number;
  symbol: string;
  direction: "BUY" | "SELL";
  volume: number;
  open_time: number;
  close_time: number;
  open_price: number;
  close_price: number;
  commission: number;
  swap: number;
  net_pnl: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function pnlColor(value: number): string {
  if (value > 0) return "text-green-600 dark:text-green-400";
  if (value < 0) return "text-red-600 dark:text-red-400";
  return "";
}

/**
 * Group raw MT5 deals by position_id and pair IN + OUT deals into one row.
 * Balance/credit deals (type >= 2) are excluded.
 * Positions with no OUT deal (still open) are excluded.
 * Result is sorted by close_time descending (latest first).
 */
function pairDeals(deals: HistoryDeal[]): PairedTrade[] {
  const tradeDeals = deals.filter((d) => d.type === 0 || d.type === 1);

  const byPosition = new Map<number, HistoryDeal[]>();
  for (const deal of tradeDeals) {
    const group = byPosition.get(deal.position_id) ?? [];
    group.push(deal);
    byPosition.set(deal.position_id, group);
  }

  const paired: PairedTrade[] = [];

  for (const posDeals of byPosition.values()) {
    const inDeals = posDeals.filter((d) => d.entry === 0);
    const outDeals = posDeals.filter((d) => d.entry === 1 || d.entry === 2);

    if (outDeals.length === 0) continue; // position still open — skip

    const inDeal = inDeals[0];
    const anchor = inDeal ?? posDeals[0];
    const lastOut = outDeals.reduce((latest, d) =>
      d.time > latest.time ? d : latest
    );

    const totalCommission = posDeals.reduce((s, d) => s + d.commission, 0);
    const totalSwap = posDeals.reduce((s, d) => s + d.swap, 0);
    const totalProfit = posDeals.reduce((s, d) => s + d.profit, 0);

    paired.push({
      position_id: anchor.position_id,
      symbol: anchor.symbol,
      direction: anchor.type === 0 ? "BUY" : "SELL",
      volume: inDeal ? inDeal.volume : outDeals.reduce((s, d) => s + d.volume, 0),
      open_time: inDeal ? inDeal.time : Math.min(...posDeals.map((d) => d.time)),
      close_time: lastOut.time,
      open_price: inDeal ? inDeal.price : 0,
      close_price: lastOut.price,
      commission: totalCommission,
      swap: totalSwap,
      net_pnl: totalProfit + totalCommission + totalSwap,
    });
  }

  return paired.sort((a, b) => b.close_time - a.close_time);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AccountHistoryView({ accountId }: Props) {
  const [deals, setDeals] = useState<HistoryDeal[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [days, setDays] = useState(90);

  const loadDeals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await accountsApi.getHistory(accountId, days);
      setDeals(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [accountId, days]);

  useEffect(() => {
    loadDeals();
  }, [loadDeals]);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      const result = await accountsApi.syncHistory(accountId, days);
      const parts: string[] = [];
      if (result.imported > 0) parts.push(`${result.imported} new`);
      if (result.updated > 0) parts.push(`${result.updated} closed`);
      const summary = parts.length > 0 ? parts.join(", ") : "0 new";
      toast.success(`Synced: ${summary} trade${result.imported + result.updated !== 1 ? "s" : ""} (${result.total_fetched} fetched)`);

      await loadDeals();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Sync failed";
      setSyncError(msg);
      toast.error(msg);
    } finally {
      setSyncing(false);
    }
  }, [accountId, days, loadDeals]);

  const rows = pairDeals(deals);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link href="/accounts">Back to Accounts</Link>
        </Button>

        <Select
          value={String(days)}
          onValueChange={(v) => setDays(parseInt(v, 10))}
        >
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="30">Last 30 days</SelectItem>
            <SelectItem value="90">Last 90 days</SelectItem>
            <SelectItem value="180">Last 180 days</SelectItem>
            <SelectItem value="3650">All time</SelectItem>
          </SelectContent>
        </Select>

        <Button size="sm" onClick={handleSync} disabled={syncing || loading}>
          {syncing ? "Syncing…" : "Sync from MT5"}
        </Button>

        {rows.length > 0 && (
          <span className="ml-auto text-sm text-muted-foreground">
            {rows.length} trade{rows.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {syncError && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          MT5 sync failed: {syncError}
        </p>
      )}

      <div className={`rounded-md border overflow-x-auto${loading ? " opacity-60" : ""}`}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Open Time</TableHead>
              <TableHead>Close Time</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Dir</TableHead>
              <TableHead className="text-right">Volume</TableHead>
              <TableHead className="text-right">Open</TableHead>
              <TableHead className="text-right">Close</TableHead>
              <TableHead className="text-right">Commission</TableHead>
              <TableHead className="text-right">Swap</TableHead>
              <TableHead className="text-right">Net P&amp;L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && !loading && (
              <TableRow>
                <TableCell
                  colSpan={10}
                  className="text-center text-muted-foreground py-8"
                >
                  No history found. Try syncing from MT5.
                </TableCell>
              </TableRow>
            )}
            {rows.map((trade) => (
              <TableRow key={trade.position_id}>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {formatDateTime(trade.open_time * 1000)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {formatDateTime(trade.close_time * 1000)}
                </TableCell>
                <TableCell className="font-medium">{trade.symbol}</TableCell>
                <TableCell>
                  {trade.direction === "BUY" ? (
                    <Badge>BUY</Badge>
                  ) : (
                    <Badge variant="destructive">SELL</Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">{trade.volume}</TableCell>
                <TableCell className="text-right font-mono">
                  {trade.open_price.toFixed(5)}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {trade.close_price.toFixed(5)}
                </TableCell>
                <TableCell className="text-right font-mono text-muted-foreground">
                  {trade.commission.toFixed(2)}
                </TableCell>
                <TableCell className="text-right font-mono text-muted-foreground">
                  {trade.swap.toFixed(2)}
                </TableCell>
                <TableCell
                  className={`text-right font-mono font-medium ${pnlColor(trade.net_pnl)}`}
                >
                  {(trade.net_pnl >= 0 ? "+" : "") + trade.net_pnl.toFixed(2)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
