"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { useTradingStore } from "@/hooks/use-trading-store";
import type { Trade } from "@/types/trading";

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number | null, digits = 5) =>
  n == null ? "—" : n.toFixed(digits);

const pnlColor = (p: number | null) => {
  if (p == null) return "";
  if (p > 0) return "text-green-600 dark:text-green-400";
  if (p < 0) return "text-red-600 dark:text-red-400";
  return "";
};

function formatISO(isoStr: string): string {
  const d = new Date(isoStr);
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = pad(d.getDate());
  const month = pad(d.getMonth() + 1);
  const year = d.getFullYear();
  let hours = d.getHours();
  const minutes = pad(d.getMinutes());
  const seconds = pad(d.getSeconds());
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  return `${day}/${month}/${year}, ${pad(hours)}:${minutes}:${seconds} ${ampm}`;
}

// ── Scorecard ─────────────────────────────────────────────────────────────────

function Scorecard({ trades }: { trades: Trade[] }) {
  const closed = trades.filter((t) => t.closed_at !== null);
  const wins = closed.filter((t) => (t.profit ?? 0) > 0);
  const totalPnl = closed.reduce((s, t) => s + (t.profit ?? 0), 0);
  const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;

  const stats = [
    { label: "Total Trades", value: trades.length },
    { label: "Closed", value: closed.length },
    {
      label: "Win Rate",
      value: `${winRate.toFixed(1)}%`,
      color:
        winRate >= 50
          ? "text-green-600 dark:text-green-400"
          : "text-red-600 dark:text-red-400",
    },
    {
      label: "Total P&L",
      value: (totalPnl >= 0 ? "+" : "") + totalPnl.toFixed(2),
      color:
        totalPnl > 0
          ? "text-green-600 dark:text-green-400"
          : totalPnl < 0
            ? "text-red-600 dark:text-red-400"
            : "",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((s) => (
        <Card key={s.label}>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">{s.label}</p>
            <p className={`text-lg font-semibold font-mono ${s.color ?? ""}`}>
              {s.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function TradesContent() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const searchParams = useSearchParams();

  const openOnly = searchParams.get("open_only") === "true";
  const dateFrom = searchParams.get("date_from") ?? "";
  const dateTo = searchParams.get("date_to") ?? "";

  function updateParams(patch: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    router.push(`/trades?${next.toString()}`);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await tradesApi.list({
        account_id: activeAccountId ?? undefined,
        open_only: openOnly,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: 500,
      });
      setTrades(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trades");
    } finally {
      setLoading(false);
    }
  }, [activeAccountId, openOnly, dateFrom, dateTo]);

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
              onChange={(e) =>
                updateParams(
                  e.target.checked
                    ? { open_only: "true", date_from: undefined, date_to: undefined }
                    : { open_only: undefined }
                )
              }
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
                  onChange={(e) => updateParams({ date_from: e.target.value || undefined })}
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
                  onChange={(e) => updateParams({ date_to: e.target.value || undefined })}
                  className="w-36 text-sm"
                />
              </div>
            </>
          )}
          <Button size="sm" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </Button>
          <span className="text-xs text-muted-foreground">
            {activeAccountId == null ? "Showing all accounts" : `Account ${activeAccountId}`}
          </span>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Scorecard */}
        {trades.length > 0 && <Scorecard trades={trades} />}

        {/* Table */}
        <div
          className={`rounded-md border overflow-x-auto${loading ? " opacity-60" : ""}`}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticket</TableHead>
                <TableHead>Opened</TableHead>
                <TableHead>Closed</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Dir</TableHead>
                <TableHead className="text-right">Volume</TableHead>
                <TableHead className="text-right">Entry</TableHead>
                {/* <TableHead className="text-right">SL</TableHead>
                <TableHead className="text-right">TP</TableHead> */}
                <TableHead className="text-right">Close</TableHead>
                <TableHead className="text-right">P&L</TableHead>
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
                  <TableCell className="font-mono text-sm">
                    {t.ticket}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {formatISO(t.opened_at)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {t.closed_at ? formatISO(t.closed_at) : "Open"}
                  </TableCell>
                  <TableCell className="font-medium">{t.symbol}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {t.source}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        t.direction === "BUY" ? "default" : "destructive"
                      }
                    >
                      {t.direction}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">{t.volume}</TableCell>
                  <TableCell className="text-right font-mono">
                    {fmt(t.entry_price)}
                  </TableCell>
                  {/* <TableCell className="text-right font-mono text-muted-foreground">
                    {fmt(t.stop_loss)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {fmt(t.take_profit)}
                  </TableCell> */}
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </SidebarInset>
  );
}

function LoadingFallback() {
  return (
    <SidebarInset>
      <AppHeader title="Trades" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    </SidebarInset>
  );
}

export default function TradesPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <TradesContent />
    </Suspense>
  );
}
