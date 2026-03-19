"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { AlertCircle, BarChart2, Loader2 } from "lucide-react";
import { useTheme } from "next-themes";
import { AppHeader } from "@/components/app-header";
import { ChartToolbar, type Timeframe, type CandleCount, type EMAPeriod } from "@/components/chart/chart-toolbar";
import { TradingChart, type OHLCVCandle } from "@/components/chart/trading-chart";
import { useTradingStore } from "@/hooks/use-trading-store";
import { apiRequest } from "@/lib/api";
import { cn } from "@/lib/utils";

// Auto-refresh intervals per timeframe (ms). H4/D1/W1 not auto-refreshed.
const AUTO_REFRESH_MS: Partial<Record<Timeframe, number>> = {
  M1: 15_000,
  M5: 60_000,
  M15: 3 * 60_000,
  M30: 5 * 60_000,
  H1: 15 * 60_000,
};

// Number keys 1–8 map to timeframes (only fires when no input is focused)
const TF_KEYS: Record<string, Timeframe> = {
  "1": "M1",
  "2": "M5",
  "3": "M15",
  "4": "M30",
  "5": "H1",
  "6": "H4",
  "7": "D1",
  "8": "W1",
};

const VALID_COUNTS = new Set<number>([200, 500, 1000]);

function ChartPageContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const symbol = params.symbol as string;
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";

  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const positions = useTradingStore((s) => s.openPositions);
  const pendingOrders = useTradingStore((s) => s.pendingOrders);

  const [timeframe, setTimeframe] = useState<Timeframe>(
    (searchParams.get("tf") as Timeframe | null) ?? "M15",
  );
  const [count, setCount] = useState<CandleCount>(() => {
    const raw = Number(searchParams.get("count"));
    return VALID_COUNTS.has(raw) ? (raw as CandleCount) : 500;
  });
  const [timezone, setTimezone] = useState<string>(() => {
    if (typeof window === "undefined") return "Asia/Bangkok";
    return localStorage.getItem("chartTimezone") ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  });
  const [emaActive, setEmaActive] = useState<EMAPeriod[]>([20, 50]);
  const [rsiActive, setRsiActive] = useState(false);
  const [candles, setCandles] = useState<OHLCVCandle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleEmaToggle(p: EMAPeriod) {
    setEmaActive((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));
  }

  // Remember last visited symbol + timezone across sessions
  useEffect(() => {
    localStorage.setItem("lastChartSymbol", symbol);
  }, [symbol]);

  useEffect(() => {
    localStorage.setItem("chartTimezone", timezone);
  }, [timezone]);

  // Sync tf + count into URL without triggering a re-render
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("tf", timeframe);
    url.searchParams.set("count", String(count));
    window.history.replaceState(null, "", url.toString());
  }, [timeframe, count]);

  const fetchCandles = useCallback(
    async (silent = false) => {
      if (!activeAccountId) return;
      if (!silent) setLoading(true);
      setError(null);
      try {
        const data = await apiRequest<OHLCVCandle[]>(
          `/market-data/${symbol}/${timeframe}?account_id=${activeAccountId}&count=${count}`,
        );
        setCandles(data);
      } catch (err) {
        if (!silent)
          setError(err instanceof Error ? err.message : "Failed to load chart data");
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [symbol, timeframe, activeAccountId, count],
  );

  // Fetch on param change (symbol, timeframe, count, account)
  useEffect(() => {
    fetchCandles();
  }, [fetchCandles]);

  // Background auto-refresh per timeframe
  useEffect(() => {
    const ms = AUTO_REFRESH_MS[timeframe];
    if (!ms || !activeAccountId) return;
    const id = setInterval(() => fetchCandles(true), ms);
    return () => clearInterval(id);
  }, [timeframe, activeAccountId, fetchCandles]);

  // Keyboard shortcuts: 1–8 switch timeframes when no input is focused
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey) return;
      const tf = TF_KEYS[e.key];
      if (tf) setTimeframe(tf);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const symbolPositions = positions.filter((p) => p.symbol === symbol);
  const symbolOrders = pendingOrders.filter((o) => o.symbol === symbol);

  return (
    <div className="flex flex-col w-full h-screen overflow-hidden">
      <AppHeader title="Chart" subtitle={symbol} />

      <ChartToolbar
        symbol={symbol}
        timeframe={timeframe}
        onTimeframeChange={setTimeframe}
        count={count}
        onCountChange={setCount}
        timezone={timezone}
        onTimezoneChange={setTimezone}
        emaActive={emaActive}
        onEmaToggle={handleEmaToggle}
        rsiActive={rsiActive}
        onRsiToggle={() => setRsiActive((v) => !v)}
        onRefresh={fetchCandles}
        isLoading={loading}
      />

      {/* Trade summary strip */}
      {(symbolPositions.length > 0 || symbolOrders.length > 0) && (
        <div className="flex items-center gap-2 px-4 py-1.5 border-b bg-card/50 overflow-x-auto shrink-0 min-h-[36px]">
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
                    : "bg-red-500/10 border-red-500/20",
                )}
              >
                <span
                  className={cn(
                    "font-bold text-[10px] px-1 py-0.5 rounded",
                    isLong ? "bg-blue-500/20 text-blue-400" : "bg-red-500/20 text-red-400",
                  )}
                >
                  {pos.type.toUpperCase()}
                </span>
                <span className="text-muted-foreground">{pos.volume}L</span>
                <span className="text-foreground/70">@{pos.open_price}</span>
                <span
                  className={cn(
                    "font-semibold",
                    isProfit ? "text-green-500 dark:text-green-400" : "text-red-500",
                  )}
                >
                  {pnlSign}${pos.profit.toFixed(2)}
                </span>
              </div>
            );
          })}

          {symbolPositions.length > 0 && symbolOrders.length > 0 && (
            <div className="h-4 w-px bg-border shrink-0" />
          )}

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

          {symbolPositions.length > 0 &&
            (() => {
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
                        : "bg-red-500/10 border-red-500/20 text-red-500",
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
              onClick={() => fetchCandles()}
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

        {/* Empty state: account set, request completed, but no candles returned */}
        {activeAccountId && !loading && !error && candles.length === 0 && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <BarChart2 className="h-8 w-8 opacity-30" />
            <p className="text-sm">
              No data for {symbol} on {timeframe}
            </p>
            <button
              onClick={() => fetchCandles()}
              className="text-xs underline underline-offset-2 hover:text-foreground"
            >
              Retry
            </button>
          </div>
        )}

        {candles.length > 0 && (
          <TradingChart
            candles={candles}
            positions={symbolPositions}
            pendingOrders={symbolOrders}
            symbol={symbol}
            isDark={isDark}
            timezone={timezone || undefined}
            emaActive={emaActive}
            rsiActive={rsiActive}
          />
        )}
      </div>
    </div>
  );
}

export default function ChartPage() {
  return (
    <Suspense>
      <ChartPageContent />
    </Suspense>
  );
}
