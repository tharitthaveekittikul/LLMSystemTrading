"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { accountsApi } from "@/lib/api/accounts";
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

function netPnl(deal: HistoryDeal): number {
  return deal.profit + deal.commission + deal.swap;
}

function pnlColor(value: number): string {
  if (value > 0) return "text-green-600 dark:text-green-400";
  if (value < 0) return "text-red-600 dark:text-red-400";
  return "";
}

function entryLabel(entry: number): string {
  if (entry === 0) return "IN";
  if (entry === 1) return "OUT";
  if (entry === 2) return "INOUT";
  return String(entry);
}

export function AccountHistoryView({ accountId }: Props) {
  const [deals, setDeals] = useState<HistoryDeal[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    try {
      const result = await accountsApi.syncHistory(accountId, days);
      toast.success(`Synced: ${result.imported} imported, ${result.total_fetched} fetched`);
      await loadDeals();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }, [accountId, days, loadDeals]);

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
          </SelectContent>
        </Select>

        <Button
          size="sm"
          onClick={handleSync}
          disabled={syncing || loading}
        >
          {syncing ? "Syncing…" : "Sync from MT5"}
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className={`rounded-md border overflow-x-auto${loading ? " opacity-60" : ""}`}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Dir</TableHead>
              <TableHead>Entry</TableHead>
              <TableHead className="text-right">Volume</TableHead>
              <TableHead className="text-right">Price</TableHead>
              <TableHead className="text-right">Commission</TableHead>
              <TableHead className="text-right">Swap</TableHead>
              <TableHead className="text-right">Net P&amp;L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {deals.length === 0 && !loading && (
              <TableRow>
                <TableCell
                  colSpan={9}
                  className="text-center text-muted-foreground py-8"
                >
                  No history found. Try syncing from MT5.
                </TableCell>
              </TableRow>
            )}
            {deals.map((deal) => {
              const net = netPnl(deal);
              return (
                <TableRow key={`${deal.ticket}-${deal.order}-${deal.time_msc}`}>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(deal.time * 1000).toLocaleString()}
                  </TableCell>
                  <TableCell className="font-medium">{deal.symbol}</TableCell>
                  <TableCell>
                    {deal.type === 0 ? (
                      <Badge>BUY</Badge>
                    ) : deal.type === 1 ? (
                      <Badge variant="destructive">SELL</Badge>
                    ) : (
                      <Badge variant="outline">{deal.type}</Badge>
                    )}
                  </TableCell>
                  <TableCell>{entryLabel(deal.entry)}</TableCell>
                  <TableCell className="text-right">{deal.volume}</TableCell>
                  <TableCell className="text-right font-mono">
                    {deal.price.toFixed(5)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {deal.commission.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {deal.swap.toFixed(2)}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono font-medium ${pnlColor(net)}`}
                  >
                    {(net >= 0 ? "+" : "") + net.toFixed(2)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
