"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { tradesApi } from "@/lib/api";
import type { Trade } from "@/types/trading";

const fmt = (n: number | null, digits = 5) =>
  n == null ? "—" : n.toFixed(digits);

const pnlColor = (p: number | null) => {
  if (p == null) return "";
  if (p > 0) return "text-green-600 dark:text-green-400";
  if (p < 0) return "text-red-600 dark:text-red-400";
  return "";
};

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openOnly, setOpenOnly] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await tradesApi.list({
        open_only: openOnly,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: 200,
      });
      setTrades(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trades");
    } finally {
      setLoading(false);
    }
  }, [openOnly, dateFrom, dateTo]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <SidebarInset>
      <AppHeader title="Trades" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="open-only"
              checked={openOnly}
              onChange={(e) => setOpenOnly(e.target.checked)}
              className="h-4 w-4"
            />
            <Label htmlFor="open-only">Open only</Label>
          </div>
          {!openOnly && (
            <>
              <div className="flex flex-col gap-1">
                <Label htmlFor="date-from" className="text-xs">
                  From
                </Label>
                <Input
                  id="date-from"
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-36 text-sm"
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="date-to" className="text-xs">
                  To
                </Label>
                <Input
                  id="date-to"
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-36 text-sm"
                />
              </div>
            </>
          )}
          <Button size="sm" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </Button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Table */}
        <div className="rounded-md border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticket</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Dir</TableHead>
                <TableHead className="text-right">Volume</TableHead>
                <TableHead className="text-right">Entry</TableHead>
                <TableHead className="text-right">SL</TableHead>
                <TableHead className="text-right">TP</TableHead>
                <TableHead className="text-right">Close</TableHead>
                <TableHead className="text-right">P&L</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Opened</TableHead>
                <TableHead>Closed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.length === 0 && !loading && (
                <TableRow>
                  <TableCell
                    colSpan={12}
                    className="text-center text-muted-foreground py-8"
                  >
                    No trades found
                  </TableCell>
                </TableRow>
              )}
              {trades.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-mono text-sm">{t.ticket}</TableCell>
                  <TableCell className="font-medium">{t.symbol}</TableCell>
                  <TableCell>
                    <Badge
                      variant={t.direction === "BUY" ? "default" : "destructive"}
                    >
                      {t.direction}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">{t.volume}</TableCell>
                  <TableCell className="text-right font-mono">
                    {fmt(t.entry_price)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {fmt(t.stop_loss)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {fmt(t.take_profit)}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {fmt(t.close_price)}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono font-medium ${pnlColor(t.profit)}`}
                  >
                    {t.profit != null
                      ? (t.profit >= 0 ? "+" : "") + t.profit.toFixed(2)
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {t.source}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(t.opened_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {t.closed_at
                      ? new Date(t.closed_at).toLocaleString()
                      : "Open"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </SidebarInset>
  );
}
