"use client";

import { useState, useEffect } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetBody,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from "@/components/ui/drawer";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loader2, TrendingUp, TrendingDown, Minus, BarChart2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api";
import { useTradingStore } from "@/hooks/use-trading-store";
import { useIsMobile } from "@/hooks/use-mobile";
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
  const isMobile = useIsMobile();
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
  const pnlColor = isProfit
    ? "text-emerald-500"
    : isLoss
      ? "text-red-500"
      : "text-muted-foreground";
  const PnlIcon = isProfit ? TrendingUp : isLoss ? TrendingDown : Minus;

  const headerTitle = (
    <div className="flex items-center gap-2 flex-wrap">
      <span>{date ?? "—"}</span>
      {entry && (
        <span className={cn("text-sm font-semibold tabular-nums", pnlColor)}>
          {pnl > 0 ? "+" : ""}
          {pnl.toFixed(2)}
        </span>
      )}
    </div>
  );

  const description = trades.length > 0
    ? `${trades.length} trade${trades.length !== 1 ? "s" : ""} closed`
    : loading
      ? "Loading…"
      : null;

  const body = (
    <DrillDownBody trades={trades} loading={loading} pnlColor={pnlColor} PnlIcon={PnlIcon} />
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={(o) => !o && onClose()} direction="bottom">
        <DrawerContent className="max-h-[90vh] flex flex-col">
          <DrawerHeader className="border-b pb-3 text-left shrink-0">
            <DrawerTitle asChild>
              <div>{headerTitle}</div>
            </DrawerTitle>
            {description && <DrawerDescription>{description}</DrawerDescription>}
          </DrawerHeader>
          <div className="flex-1 overflow-auto">{body}</div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle asChild>
            <div>{headerTitle}</div>
          </SheetTitle>
          {description && <SheetDescription>{description}</SheetDescription>}
        </SheetHeader>
        <SheetBody className="p-0">{body}</SheetBody>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Body content ───────────────────────────────────────────────────── */

function DrillDownBody({
  trades,
  loading,
  pnlColor,
  PnlIcon,
}: {
  trades: Trade[];
  loading: boolean;
  pnlColor: string;
  PnlIcon: React.ElementType;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Loading trades…</span>
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20 text-muted-foreground">
        <BarChart2 className="h-10 w-10 opacity-20" />
        <p className="text-sm">No trades found for this day</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/40 hover:bg-muted/40 sticky top-0">
          <TableHead className="text-xs">Symbol</TableHead>
          <TableHead className="text-xs">Dir</TableHead>
          <TableHead className="text-xs">Vol</TableHead>
          <TableHead className="text-xs">Entry</TableHead>
          <TableHead className="text-xs">Exit</TableHead>
          <TableHead className="text-xs">P&amp;L</TableHead>
          <TableHead className="text-xs">Duration</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.map((t) => {
          const tProfit = t.profit ?? 0;
          const tProfitColor =
            tProfit > 0
              ? "text-emerald-500"
              : tProfit < 0
                ? "text-red-500"
                : "text-muted-foreground";

          return (
            <TableRow key={t.id} className="hover:bg-muted/30">
              <TableCell className="font-mono text-xs font-medium">
                {t.symbol}
              </TableCell>
              <TableCell>
                <Badge
                  variant={t.direction === "BUY" ? "outline" : "secondary"}
                  className={cn(
                    "text-xs px-1.5 py-0",
                    t.direction === "BUY"
                      ? "border-emerald-500/40 text-emerald-500"
                      : "border-red-500/40 text-red-500",
                  )}
                >
                  {t.direction}
                </Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {t.volume}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {t.entry_price}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {t.close_price ?? "—"}
              </TableCell>
              <TableCell className={cn("text-xs font-semibold tabular-nums", tProfitColor)}>
                {t.profit != null
                  ? `${tProfit > 0 ? "+" : ""}${tProfit.toFixed(2)}`
                  : "—"}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatDuration(t.opened_at, t.closed_at)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
