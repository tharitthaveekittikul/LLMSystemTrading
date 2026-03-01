"use client";

import { useCallback, useEffect, useState } from "react";
import { BacktestConfigForm } from "@/components/backtest/backtest-config-form";
import { BacktestRunList } from "@/components/backtest/backtest-run-list";
import { BacktestResults } from "@/components/backtest/backtest-results";
import { backtestApi, API_BASE_URL } from "@/lib/api";
import type { BacktestRunSummary } from "@/types/trading";

interface StrategyItem {
  id: number;
  name: string;
  timeframe: string;
  strategy_type: string;
}

export default function BacktestPage() {
  const [runs, setRuns] = useState<BacktestRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<BacktestRunSummary | null>(null);
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);

  const refreshRuns = useCallback(async () => {
    try {
      const latest = await backtestApi.listRuns({ limit: 50 });
      setRuns(latest);
      setSelectedRun((prev) => {
        if (!prev) return prev;
        const updated = latest.find((r) => r.id === prev.id);
        return updated ?? prev;
      });
    } catch {
      // silently ignore network errors during polling
    }
  }, []);

  // Initial data load
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/v1/strategies`)
      .then((r) => r.json())
      .then((data: StrategyItem[]) => setStrategies(Array.isArray(data) ? data : []))
      .catch(() => {});

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshRuns();
  }, [refreshRuns]);

  // Polling fallback while any run is active
  useEffect(() => {
    const hasActive = runs.some(
      (r) => r.status === "pending" || r.status === "running",
    );
    if (!hasActive) return;
    const id = setInterval(refreshRuns, 3000);
    return () => clearInterval(id);
  }, [runs, refreshRuns]);

  const handleRunCreated = useCallback((run: BacktestRunSummary) => {
    setRuns((prev) => [run, ...prev]);
    setSelectedRun(run);
  }, []);

  return (
    <div className="flex h-full min-h-0">
      {/* ── Left panel: Config + History ── */}
      <div className="w-72 shrink-0 border-r flex flex-col h-full overflow-hidden">
        <div className="px-4 py-3 border-b shrink-0">
          <h1 className="text-sm font-semibold">Strategy Tester</h1>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Backtest on historical OHLCV data
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
          <BacktestConfigForm strategies={strategies} onRunCreated={handleRunCreated} />

          <div>
            <h2 className="text-xs font-medium mb-1.5">Past Runs</h2>
            <BacktestRunList
              runs={runs}
              selectedRunId={selectedRun?.id ?? null}
              onSelect={setSelectedRun}
            />
          </div>
        </div>
      </div>

      {/* ── Right panel: Results ── */}
      <div className="flex-1 overflow-y-auto p-5">
        {selectedRun ? (
          <BacktestResults key={selectedRun.id} run={selectedRun} />
        ) : (
          <div className="flex items-center justify-center h-full text-center text-muted-foreground">
            <div>
              <p className="text-base font-medium">Select or run a backtest</p>
              <p className="text-xs mt-1">
                Configure a strategy and date range on the left, then click Run Backtest.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
