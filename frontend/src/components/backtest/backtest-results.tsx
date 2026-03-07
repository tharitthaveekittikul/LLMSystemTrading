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
import { MonthlyHeatmap } from "./monthly-heatmap";
import { BacktestTradeTable } from "./backtest-trade-table";

interface Props {
  run: BacktestRunSummary;
}

type TabId = "equity" | "monthly" | "trades";

const TABS: { id: TabId; label: string }[] = [
  { id: "equity", label: "Equity Curve" },
  { id: "monthly", label: "Monthly P&L" },
  { id: "trades", label: "Trades" },
];

export function BacktestResults({ run }: Props) {
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [equity, setEquity] = useState<BacktestEquityPoint[]>([]);
  const [monthly, setMonthly] = useState<BacktestMonthlyPnl[]>([]);
  const [activeTab, setActiveTab] = useState<TabId>("equity");

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
          <EquityCurveChart
            data={equity}
            initialBalance={run.initial_balance}
          />
        )}
        {activeTab === "monthly" && <MonthlyHeatmap data={monthly} />}
        {activeTab === "trades" && <BacktestTradeTable trades={trades} />}
      </div>
    </div>
  );
}
