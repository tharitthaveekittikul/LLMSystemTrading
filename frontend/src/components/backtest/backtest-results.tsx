"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { backtestApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type {
  BacktestEquityPoint,
  BacktestMonthlyPnl,
  BacktestRunSummary,
  BacktestTrade,
} from "@/types/trading";
import { BacktestMetricsGrid } from "./backtest-metrics-grid";
import { EquityCurveChart } from "./equity-curve-chart";
import { DrawdownChart } from "./drawdown-chart";
import { MonthlyHeatmap } from "./monthly-heatmap";
import { BacktestTradeTable } from "./backtest-trade-table";
import { TradingChart, type OHLCVCandle } from "@/components/chart/trading-chart";
import type { TradeMarker } from "@/types/trading";

interface Props {
  run: BacktestRunSummary;
}

type TabId = "equity" | "monthly" | "trades" | "chart";

const TABS: { id: TabId; label: string }[] = [
  { id: "equity", label: "Equity Curve" },
  { id: "monthly", label: "Monthly P&L" },
  { id: "trades", label: "Trades" },
  { id: "chart", label: "Chart" },
];

export function BacktestResults({ run }: Props) {
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [equity, setEquity] = useState<BacktestEquityPoint[]>([]);
  const [monthly, setMonthly] = useState<BacktestMonthlyPnl[]>([]);
  const [activeTab, setActiveTab] = useState<TabId>("equity");
  const [candles, setCandles] = useState<OHLCVCandle[]>([]);
  const [candlesLoading, setCandlesLoading] = useState(false);
  const [focusTime, setFocusTime] = useState<number | undefined>();

  useEffect(() => {
    if (run.status !== "completed") return;
    (async () => {
      try {
        const [t, e, m] = await Promise.all([
          backtestApi.getTrades(run.id, { limit: 1000 }),
          backtestApi.getEquityCurve(run.id),
          backtestApi.getMonthlyPnl(run.id),
        ]);
        setTrades(t);
        setEquity(e);
        setMonthly(m);
      } catch (err) {
        console.error("[BacktestResults] Failed to load results:", err);
      }
    })();
  }, [run.id, run.status]);

  useEffect(() => {
    if (activeTab !== "chart" || candles.length > 0 || run.status !== "completed") return;
    setCandlesLoading(true);
    backtestApi
      .getCandles(run.id)
      .then(setCandles)
      .catch(() => {
        // silently show empty chart state
      })
      .finally(() => setCandlesLoading(false));
  }, [activeTab, run.id, run.status, candles.length]);

  if (run.status === "pending" || run.status === "running") {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="text-center">
          <p className="font-medium">
            {run.status === "pending"
              ? "Backtest queued…"
              : "Running backtest…"}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {run.symbol} · {run.timeframe} · {run.start_date.slice(0, 10)} →{" "}
            {run.end_date.slice(0, 10)}
          </p>
        </div>
        <div className="w-64 h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: `${run.progress_pct}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground">{run.progress_pct}%</p>
      </div>
    );
  }

  if (run.status === "failed") {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center text-destructive">
          <p className="font-medium">Backtest failed</p>
          <p className="text-xs mt-1 max-w-sm">
            {run.error_message ?? "Unknown error"}
          </p>
        </div>
      </div>
    );
  }

  const tradeTabLabel = `Trades (${run.total_trades ?? 0})`;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-medium text-muted-foreground">
            {run.symbol} · {run.timeframe} · {run.start_date.slice(0, 10)} →{" "}
            {run.end_date.slice(0, 10)}
            {" · "}
            {run.execution_mode === "close_price"
              ? "Close Price"
              : "Intra-Candle"}
          </p>
          <Button variant="outline" size="sm" asChild>
            <Link href={`/backtest/${run.id}/analytics`}>View Analytics</Link>
          </Button>
        </div>
        <BacktestMetricsGrid run={run} />
      </div>

      <div>
        {/* Tab bar */}
        <div className="flex gap-0.5 border-b mb-3">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium rounded-t transition-colors",
                activeTab === tab.id
                  ? "bg-background border border-b-background border-t border-l border-r -mb-px text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.id === "trades" ? tradeTabLabel : tab.label}
            </button>
          ))}
        </div>

        {/* Tab panels */}
        {activeTab === "equity" && (
          <div>
            <EquityCurveChart
              data={equity}
              initialBalance={run.initial_balance}
            />
            <DrawdownChart runId={run.id} />
          </div>
        )}
        {activeTab === "monthly" && <MonthlyHeatmap data={monthly} />}
        {activeTab === "trades" && (
          <BacktestTradeTable
            trades={trades}
            onRowClick={(t) => {
              setFocusTime(new Date(t.entry_time).getTime() / 1000);
              setActiveTab("chart");
            }}
          />
        )}
        {activeTab === "chart" && (
          <div className="h-[520px] w-full rounded-md border overflow-hidden">
            {candlesLoading ? (
              <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
                Loading candles…
              </div>
            ) : candles.length === 0 ? (
              <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
                No candle data available for this run
              </div>
            ) : (
              <TradingChart
                candles={candles}
                positions={[]}
                pendingOrders={[]}
                symbol={run.symbol}
                viewResetKey={`backtest-${run.id}`}
                focusTime={focusTime}
                tradeMarkers={trades.map<TradeMarker>((t) => ({
                  entry_time: new Date(t.entry_time).getTime() / 1000,
                  exit_time: t.exit_time
                    ? new Date(t.exit_time).getTime() / 1000
                    : null,
                  direction: t.direction as "BUY" | "SELL",
                  profit: t.profit ?? null,
                  exit_reason: t.exit_reason ?? null,
                }))}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
