"use client";

import { useEffect, useState, useCallback, useMemo, useRef, Suspense } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, BarChart2, Loader2, Radio } from "lucide-react";
import { useTheme } from "next-themes";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountSelector } from "@/components/dashboard/account-selector";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ChartToolbar,
  type Timeframe,
  type CandleCount,
  type EMAPeriod,
} from "@/components/chart/chart-toolbar";
import {
  TradingChart,
  type OHLCVCandle,
} from "@/components/chart/trading-chart";
import { useTradingStore } from "@/hooks/use-trading-store";
import { useWebSocket } from "@/hooks/use-websocket";
import { apiRequest, ApiError } from "@/lib/api";
import type { TickUpdateData } from "@/types/trading";
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
const REQUEST_TIMEOUT_MS = 15_000;

interface ChartDataResponse {
  symbol: string;
  candles: OHLCVCandle[];
}

interface FriendlyError {
  title: string;
  detail?: string;
}

function toFriendlyError(err: unknown): FriendlyError {
  if (err instanceof DOMException && err.name === "AbortError") {
    return {
      title: "Request timed out",
      detail: "The broker connection is taking too long to respond.",
    };
  }
  if (err instanceof ApiError) {
    if (err.status === 503) return { title: "Broker unavailable", detail: err.message };
    if (err.status === 404) return { title: "Account not found", detail: err.message };
    if (err.status === 400) return { title: "Invalid request", detail: err.message };
    if (err.status === 0) return { title: "Network error", detail: err.message };
    return { title: "Couldn't load chart data", detail: err.message };
  }
  return {
    title: "Couldn't load chart data",
    detail: err instanceof Error ? err.message : undefined,
  };
}

function ChartSkeleton() {
  // Deterministic pseudo-random bar heights so the skeleton doesn't look like
  // a repeating pattern, without using Math.random() (stable across re-renders).
  const heights = useMemo(
    () => Array.from({ length: 40 }, (_, i) => 20 + ((i * 37) % 60)),
    [],
  );
  return (
    <div className="absolute inset-0 flex items-end gap-1 px-6 pb-10 pt-16 opacity-60">
      {heights.map((h, i) => (
        <Skeleton key={i} className="flex-1" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

function ChartPageContent() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const symbol = params.symbol as string;
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";

  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const positions = useTradingStore((s) => s.openPositions);
  const pendingOrders = useTradingStore((s) => s.pendingOrders);

  const [timeframe, setTimeframe] = useState<Timeframe>(
    (searchParams.get("tf") as Timeframe | null) ?? "H1",
  );
  const [count, setCount] = useState<CandleCount>(() => {
    const raw = Number(searchParams.get("count"));
    return VALID_COUNTS.has(raw) ? (raw as CandleCount) : 1000;
  });
  const [timezone, setTimezone] = useState<string>(() => {
    if (typeof window === "undefined") return "Asia/Bangkok";
    return (
      localStorage.getItem("chartTimezone") ??
      Intl.DateTimeFormat().resolvedOptions().timeZone
    );
  });
  const [emaActive, setEmaActive] = useState<EMAPeriod[]>([20, 50]);
  const [rsiActive, setRsiActive] = useState(true);
  const [candles, setCandles] = useState<OHLCVCandle[]>([]);
  // The broker's real symbol name (e.g. "XAUUSD.s"), resolved server-side.
  // Positions/pending orders/markers must filter against THIS, not the raw
  // URL segment, since MT5 reports the suffixed name.
  const [resolvedSymbol, setResolvedSymbol] = useState(symbol);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [stale, setStale] = useState(false);
  const [lastTick, setLastTick] = useState<TickUpdateData | null>(null);

  function handleEmaToggle(p: EMAPeriod) {
    setEmaActive((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );
  }

  // Remember last visited symbol + timezone across sessions (prefer the
  // resolved broker symbol once known, so next visit skips resolution).
  useEffect(() => {
    localStorage.setItem("lastChartSymbol", resolvedSymbol || symbol);
  }, [symbol, resolvedSymbol]);

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
      try {
        const data = await apiRequest<ChartDataResponse>(
          `/market-data/${symbol}/${timeframe}?account_id=${activeAccountId}&count=${count}`,
          { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) },
        );
        setCandles(data.candles);
        setResolvedSymbol(data.symbol);
        setError(null);
        setStale(false);
      } catch (err) {
        if (!silent) {
          setError(toFriendlyError(err));
        } else {
          // Background refresh failures shouldn't blank out a working chart —
          // surface a small "stale" indicator instead of a scary error overlay.
          setStale(true);
          console.error("[chart] background refresh failed:", err);
        }
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

  // Self-heal the URL once the broker's real symbol name is known, so a
  // bookmarked/typed bare name (e.g. "XAUUSD") settles on the resolved one
  // (e.g. "XAUUSD.s") for future visits and copy-paste links.
  useEffect(() => {
    if (!resolvedSymbol || resolvedSymbol === symbol) return;
    const url = new URL(window.location.href);
    router.replace(`/chart/${resolvedSymbol}${url.search}`);
  }, [resolvedSymbol, symbol, router]);

  // Keyboard shortcuts: 1–8 switch timeframes when no input is focused
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const tag = target.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        target.isContentEditable ||
        e.metaKey ||
        e.ctrlKey
      )
        return;
      const tf = TF_KEYS[e.key];
      if (tf) setTimeframe(tf);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Live price: subscribe to tick_update for the resolved symbol over the
  // dashboard WebSocket (backend broadcasts every ~5s while watched).
  const resolvedSymbolRef = useRef(resolvedSymbol);
  useEffect(() => {
    resolvedSymbolRef.current = resolvedSymbol;
  }, [resolvedSymbol]);

  const wsHandlers = useRef({
    tick_update: (data: unknown) => {
      const d = data as TickUpdateData;
      setLastTick((prev) => (d.symbol === resolvedSymbolRef.current ? d : prev));
    },
  });

  const { isConnected, send } = useWebSocket(activeAccountId, wsHandlers.current);

  useEffect(() => {
    setLastTick(null);
    if (isConnected && resolvedSymbol) {
      send({ action: "watch_symbol", symbol: resolvedSymbol });
    }
  }, [isConnected, resolvedSymbol, send]);

  const symbolPositions = positions.filter((p) => p.symbol === resolvedSymbol);
  const symbolOrders = pendingOrders.filter((o) => o.symbol === resolvedSymbol);

  return (
    <SidebarInset className="flex flex-col h-screen overflow-hidden" data-layout="fullscreen">
      <AppHeader title="Chart" subtitle={resolvedSymbol} />

      <ChartToolbar
        symbol={symbol}
        activeAccountId={activeAccountId}
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
                    isLong
                      ? "bg-blue-500/20 text-blue-400"
                      : "bg-red-500/20 text-red-400",
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
                      : "text-red-500",
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
              const total = symbolPositions.reduce(
                (sum, p) => sum + p.profit,
                0,
              );
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
        {/* Live connection badge */}
        {activeAccountId && candles.length > 0 && (
          <div className="absolute top-2 right-3 z-10 flex items-center gap-2">
            {stale && (
              <span className="text-[10px] text-amber-500/90 font-medium">
                Live updates paused
              </span>
            )}
            <div
              className={cn(
                "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                isConnected
                  ? "border-green-500/30 bg-green-500/10 text-green-500 dark:text-green-400"
                  : "border-border bg-muted/50 text-muted-foreground",
              )}
              title={isConnected ? "Receiving live price updates" : "Live updates disconnected"}
            >
              <Radio className={cn("h-2.5 w-2.5", isConnected && "animate-pulse")} />
              {isConnected ? "Live" : "Offline"}
            </div>
          </div>
        )}

        {loading && candles.length === 0 && <ChartSkeleton />}

        {loading && candles.length > 0 && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && !loading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 text-center px-6">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <p className="text-sm font-medium text-foreground">{error.title}</p>
            {error.detail && (
              <p className="text-xs text-muted-foreground max-w-md">{error.detail}</p>
            )}
            <button
              onClick={() => fetchCandles()}
              className="mt-1 text-xs font-medium underline underline-offset-2 hover:text-foreground text-muted-foreground"
            >
              Retry
            </button>
          </div>
        )}

        {!activeAccountId && !loading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 text-center px-6">
            <BarChart2 className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm font-medium text-foreground">
              Select an account to load chart data
            </p>
            <AccountSelector />
          </div>
        )}

        {/* Empty state: account set, request completed, but no candles returned */}
        {activeAccountId && !loading && !error && candles.length === 0 && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <BarChart2 className="h-8 w-8 opacity-30" />
            <p className="text-sm">
              No data for {resolvedSymbol} on {timeframe}
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
            symbol={resolvedSymbol}
            isDark={isDark}
            timezone={timezone || undefined}
            viewResetKey={`${resolvedSymbol}-${timeframe}-${count}`}
            emaActive={emaActive}
            rsiActive={rsiActive}
            lastTick={lastTick}
          />
        )}
      </div>
    </SidebarInset>
  );
}

export default function ChartPage() {
  return (
    <Suspense>
      <ChartPageContent />
    </Suspense>
  );
}
