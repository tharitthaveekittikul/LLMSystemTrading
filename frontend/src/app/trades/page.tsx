"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { format, parseISO } from "date-fns";
import type { DateRange } from "react-day-picker";
import { CalendarIcon, RefreshCw, Inbox } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Calendar } from "@/components/ui/calendar";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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
import { formatDateTime } from "@/lib/date";
import type { Trade } from "@/types/trading";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number | null, digits = 5) =>
  n == null ? "—" : n.toFixed(digits);

const pnlColor = (p: number | null) => {
  if (p == null) return "";
  if (p > 0) return "text-green-600 dark:text-green-400";
  if (p < 0) return "text-red-600 dark:text-red-400";
  return "";
};

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
        <Card key={s.label} className="border-l-2 border-l-primary shadow-sm">
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

// ── Skeleton rows ─────────────────────────────────────────────────────────────

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 9 }).map((_, j) => (
            <TableCell key={j}>
              <div className="h-4 rounded bg-muted animate-pulse w-16" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function TradesContent() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
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
      setInitialLoad(false);
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
        <div className="flex flex-col sm:flex-row sm:items-end gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Checkbox
              id="open-only"
              checked={openOnly}
              onCheckedChange={(checked) =>
                updateParams(
                  checked
                    ? {
                        open_only: "true",
                        date_from: undefined,
                        date_to: undefined,
                      }
                    : { open_only: undefined },
                )
              }
            />
            <Label htmlFor="open-only">Open only</Label>
          </div>
          {!openOnly && (
            <div className="flex flex-col gap-1">
              <Label className="text-xs">Date Range</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    id="date-range"
                    variant="outline"
                    className={cn(
                      "w-full sm:w-64 justify-start text-left text-sm font-normal",
                      !dateFrom && !dateTo && "text-muted-foreground",
                    )}
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    {dateFrom && dateTo
                      ? `${format(parseISO(dateFrom), "MMM d, yyyy")} – ${format(parseISO(dateTo), "MMM d, yyyy")}`
                      : dateFrom
                        ? `From ${format(parseISO(dateFrom), "MMM d, yyyy")}`
                        : "Pick a date range"}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="range"
                    captionLayout="dropdown"
                    defaultMonth={dateFrom ? parseISO(dateFrom) : new Date()}
                    selected={
                      {
                        from: dateFrom ? parseISO(dateFrom) : undefined,
                        to: dateTo ? parseISO(dateTo) : undefined,
                      } as DateRange
                    }
                    onSelect={(range) => {
                      updateParams({
                        date_from: range?.from
                          ? format(range.from, "yyyy-MM-dd")
                          : undefined,
                        date_to: range?.to
                          ? format(range.to, "yyyy-MM-dd")
                          : undefined,
                      });
                    }}
                    numberOfMonths={2}
                  />
                  {(dateFrom || dateTo) && (
                    <div className="border-t p-3 flex justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          updateParams({
                            date_from: undefined,
                            date_to: undefined,
                          })
                        }
                      >
                        Clear
                      </Button>
                    </div>
                  )}
                </PopoverContent>
              </Popover>
            </div>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", loading && "animate-spin")}
            />
            {loading ? "Loading…" : "Refresh"}
          </Button>
          <span className="text-xs text-muted-foreground">
            {activeAccountId == null
              ? "Showing all accounts"
              : `Account ${activeAccountId}`}
          </span>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Scorecard */}
        {trades.length > 0 && <Scorecard trades={trades} />}

        {/* Scroll hint — only on mobile */}
        {trades.length > 0 && (
          <p className="text-xs text-muted-foreground sm:hidden">
            ← Swipe to see all columns
          </p>
        )}

        {/* Table */}
        <div
          className={cn(
            "rounded-md border overflow-x-auto",
            !initialLoad && loading && "opacity-60",
          )}
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
                <TableHead className="text-right">Close</TableHead>
                <TableHead className="text-right">P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {initialLoad && loading ? (
                <SkeletonRows />
              ) : trades.length === 0 && !loading ? (
                <TableRow>
                  <TableCell colSpan={10} className="text-center py-16">
                    <div className="flex flex-col items-center gap-2 text-muted-foreground">
                      <Inbox className="h-8 w-8 opacity-40" />
                      <span className="text-sm">No trades found</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                trades.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-mono text-sm">
                      {t.ticket}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {formatDateTime(t.opened_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {t.closed_at ? (
                        formatDateTime(t.closed_at)
                      ) : (
                        <Badge
                          variant="outline"
                          className="text-xs border-green-500 text-green-600 dark:text-green-400"
                        >
                          Open
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-medium">{t.symbol}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {t.source}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={cn(
                          "text-xs font-medium border-0",
                          t.direction === "BUY"
                            ? "bg-green-500 hover:bg-green-600 text-white"
                            : "bg-red-500 hover:bg-red-600 text-white",
                        )}
                      >
                        {t.direction}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">{t.volume}</TableCell>
                    <TableCell className="text-right font-mono">
                      {fmt(t.entry_price)}
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
                  </TableRow>
                ))
              )}
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
