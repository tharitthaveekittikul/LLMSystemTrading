"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { AlertCircle, Loader2 } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { ChartToolbar, type Timeframe } from "@/components/chart/chart-toolbar";
import {
  TradingChart,
  type OHLCVCandle,
} from "@/components/chart/trading-chart";
import { useTradingStore } from "@/hooks/use-trading-store";
import { apiRequest } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ChartPage() {
  const params = useParams();
  const symbol = params.symbol as string;

  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const positions = useTradingStore((s) => s.openPositions);
  const pendingOrders = useTradingStore((s) => s.pendingOrders);

  const [timeframe, setTimeframe] = useState<Timeframe>("M15");
  const [candles, setCandles] = useState<OHLCVCandle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCandles = useCallback(async () => {
    if (!activeAccountId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<OHLCVCandle[]>(
        `/market-data/${symbol}/${timeframe}?account_id=${activeAccountId}&count=300`,
      );
      setCandles(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load chart data",
      );
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe, activeAccountId]);

  useEffect(() => {
    fetchCandles();
  }, [fetchCandles]);

  // Filter positions / pending orders for this symbol
  const symbolPositions = positions.filter((p) => p.symbol === symbol);
  const symbolOrders = pendingOrders.filter((o) => o.symbol === symbol);

  return (
    <div className="flex flex-col w-full h-screen overflow-hidden">
      <AppHeader title="Chart" subtitle={symbol} />
      {/* Chart toolbar */}
      <ChartToolbar
        symbol={symbol}
        timeframe={timeframe}
        onTimeframeChange={setTimeframe}
        onRefresh={fetchCandles}
        isLoading={loading}
      />

      {/* Trade summary strip */}
      {(symbolPositions.length > 0 || symbolOrders.length > 0) && (
        <div className="flex items-center gap-2 px-4 py-1.5 border-b bg-card/50 overflow-x-auto shrink-0 min-h-[36px]">
          {/* Open positions */}
          {symbolPositions.map((pos) => {
            const isProfit = pos.profit >= 0;
            const pnlSign = isProfit ? "+" : "";
            const isLong = pos.type === "buy";
            return (
              <div
                key={pos.ticket}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs shrink-0",
                  isProfit
                    ? "bg-green-500/10 border-green-500/20"
                    : "bg-red-500/10 border-red-500/20"
                )}
              >
                <span
                  className={cn(
                    "font-bold text-[10px] px-1 py-0.5 rounded",
                    isLong
                      ? "bg-blue-500/20 text-blue-400"
                      : "bg-red-500/20 text-red-400"
                  )}
                >
                  {pos.type.toUpperCase()}
                </span>
                <span className="text-muted-foreground">{pos.volume}L</span>
                <span className="text-foreground/70">@{pos.open_price}</span>
                <span
                  className={cn(
                    "font-semibold",
                    isProfit
                      ? "text-green-500 dark:text-green-400"
                      : "text-red-500"
                  )}
                >
                  {pnlSign}${pos.profit.toFixed(2)}
                </span>
              </div>
            );
          })}

          {/* Divider */}
          {symbolPositions.length > 0 && symbolOrders.length > 0 && (
            <div className="h-4 w-px bg-border shrink-0" />
          )}

          {/* Pending orders */}
          {symbolOrders.map((order) => (
            <div
              key={order.ticket}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-dashed border-border bg-muted/40 text-xs shrink-0"
            >
              <span className="font-medium text-muted-foreground text-[10px] px-1 py-0.5 rounded bg-muted">
                {order.type.replace(/_/g, " ").toUpperCase()}
              </span>
              <span className="text-muted-foreground">{order.volume}L</span>
              <span className="text-muted-foreground">@{order.price}</span>
            </div>
          ))}

          {/* Total P/L */}
          {symbolPositions.length > 0 && (() => {
            const total = symbolPositions.reduce((sum, p) => sum + p.profit, 0);
            const isProfit = total >= 0;
            return (
              <>
                <div className="flex-1" />
                <div
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-semibold shrink-0",
                    isProfit
                      ? "bg-green-500/10 border-green-500/20 text-green-500 dark:text-green-400"
                      : "bg-red-500/10 border-red-500/20 text-red-500"
                  )}
                >
                  <span className="text-muted-foreground font-normal text-[10px]">
                    Total P/L
                  </span>
                  {isProfit ? "+" : ""}${total.toFixed(2)}
                </div>
              </>
            );
          })()}
        </div>
      )}

      {/* Chart area */}
      <div className="relative flex-1 min-h-0">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && !loading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm">{error}</p>
            <button
              onClick={fetchCandles}
              className="text-xs underline underline-offset-2 hover:text-foreground"
            >
              Retry
            </button>
          </div>
        )}

        {!activeAccountId && !loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center text-muted-foreground text-sm">
            Select an account on the Dashboard to load chart data.
          </div>
        )}

        {candles.length > 0 && (
          <TradingChart
            candles={candles}
            positions={symbolPositions}
            pendingOrders={symbolOrders}
            symbol={symbol}
          />
        )}
      </div>
    </div>
  );
}
