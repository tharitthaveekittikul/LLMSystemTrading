"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { optimizationApi } from "@/lib/api";
import type { OptimizationRunSummary, OptimizationResult, OptimizationResultsPage } from "@/types/trading";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  Trophy,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

const PAGE_SIZE = 50;

const METRIC_LABELS: Record<string, string> = {
  sharpe_ratio: "Sharpe",
  profit_factor: "Profit Factor",
  total_return_pct: "Return %",
  win_rate: "Win Rate",
  expectancy: "Expectancy",
  max_drawdown_pct: "Max DD %",
  recovery_factor: "Recovery",
  sortino_ratio: "Sortino",
};

const ALL_METRICS = [
  "total_trades",
  "win_rate",
  "profit_factor",
  "sharpe_ratio",
  "sortino_ratio",
  "total_return_pct",
  "expectancy",
  "max_drawdown_pct",
  "recovery_factor",
  "avg_win",
  "avg_loss",
] as const;

function fmt(val: number | null | undefined, key: string): string {
  if (val == null) return "—";
  if (key === "win_rate") return `${(val * 100).toFixed(1)}%`;
  if (key === "total_return_pct" || key === "max_drawdown_pct") return `${val.toFixed(2)}%`;
  return val.toFixed(3);
}

function fmtEta(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export default function OptimizeResultPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [run, setRun] = useState<OptimizationRunSummary | null>(null);
  const [sortKey, setSortKey] = useState<string>("");
  const [sortDesc, setSortDesc] = useState(true);

  // Paginated results state
  const [resultsPage, setResultsPage] = useState<OptimizationResultsPage | null>(null);
  const [page, setPage] = useState(1);
  const [loadingResults, setLoadingResults] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await optimizationApi.get(Number(id));
      setRun(data);
      if (!sortKey) setSortKey(data.optimize_metric);
    } catch { /* ignore */ }
  }, [id, sortKey]);

  const loadResults = useCallback(async (p: number, sk: string, desc: boolean) => {
    setLoadingResults(true);
    try {
      const data = await optimizationApi.getResults(Number(id), {
        page: p,
        page_size: PAGE_SIZE,
        sort_by: sk || "sharpe_ratio",
        order: desc ? "desc" : "asc",
      });
      setResultsPage(data);
    } catch { /* ignore */ } finally {
      setLoadingResults(false);
    }
  }, [id]);

  useEffect(() => { void refresh(); }, [refresh]);

  // Load results when run is completed or when sort/page changes
  useEffect(() => {
    if (run?.status === "completed" && sortKey) {
      void loadResults(page, sortKey, sortDesc);
    }
  }, [run?.status, page, sortKey, sortDesc, loadResults]);

  // Poll while running
  useEffect(() => {
    if (!run || (run.status !== "pending" && run.status !== "running")) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [run, refresh]);

  if (!run) {
    return (
      <SidebarInset>
        <AppHeader title="Optimization" subtitle="Loading…" showAccountSelector={false} showConnectionStatus={false} />
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </SidebarInset>
    );
  }

  const paramNames = Object.keys(run.param_grid);
  const results: OptimizationResult[] = resultsPage?.results ?? [];

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(true); setPage(1); }
  };

  return (
    <SidebarInset>
      <AppHeader
        title={`Optimization #${run.id}`}
        subtitle={`${run.symbol} · ${run.timeframe} — optimizing ${METRIC_LABELS[run.optimize_metric] ?? run.optimize_metric}`}
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="p-5 space-y-4">

        {/* ── Header row ── */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <StatusBadge status={run.status} />
          {(run.status === "pending" || run.status === "running") && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>{run.completed_combinations}/{run.total_combinations} combos</span>
              <div className="w-32 bg-muted rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all"
                  style={{ width: `${run.progress_pct}%` }}
                />
              </div>
              <span>{run.progress_pct}%</span>
              {run.estimated_seconds_remaining != null && run.estimated_seconds_remaining > 0 && (
                <span className="text-xs text-muted-foreground">
                  ~{fmtEta(run.estimated_seconds_remaining)} left
                </span>
              )}
              <span className="text-xs text-muted-foreground">({run.max_workers}w)</span>
            </div>
          )}
          {run.status === "completed" && (
            <span className="text-sm text-muted-foreground">
              {resultsPage?.total ?? "…"} results · sorted by {METRIC_LABELS[run.optimize_metric] ?? run.optimize_metric}
            </span>
          )}
        </div>

        {/* ── Best params banner ── */}
        {run.status === "completed" && run.best_params && Object.keys(run.best_params).length > 0 && (
          <div className="border border-green-500/30 bg-green-500/5 rounded-lg p-3 flex items-start gap-2">
            <Trophy className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-green-700 dark:text-green-400">Best Configuration</p>
              <div className="flex flex-wrap gap-2 mt-1">
                {Object.entries(run.best_params).map(([k, v]) => (
                  <span key={k} className="text-xs bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 rounded px-2 py-0.5">
                    {k} = {String(v)}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {run.status === "failed" && (
          <div className="border border-destructive/30 bg-destructive/5 rounded-lg p-3 text-sm text-destructive">
            {run.error_message || "Optimization failed with an unknown error."}
          </div>
        )}

        {/* ── Results table ── */}
        {(results.length > 0 || loadingResults) && (
          <div className="space-y-2">
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    <th className="text-left px-3 py-2 font-medium text-muted-foreground">#</th>
                    {paramNames.map((p) => (
                      <th key={p} className="text-left px-3 py-2 font-medium text-muted-foreground whitespace-nowrap">
                        {p}
                      </th>
                    ))}
                    {ALL_METRICS.map((m) => (
                      <th
                        key={m}
                        className="text-right px-3 py-2 font-medium text-muted-foreground whitespace-nowrap cursor-pointer hover:text-foreground select-none"
                        onClick={() => toggleSort(m)}
                      >
                        {METRIC_LABELS[m] ?? m}
                        {sortKey === m && (sortDesc ? " ↓" : " ↑")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loadingResults ? (
                    <tr>
                      <td colSpan={paramNames.length + ALL_METRICS.length + 1} className="text-center py-6 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Loading…
                      </td>
                    </tr>
                  ) : results.map((r, i) => {
                    const globalRank = (page - 1) * PAGE_SIZE + i;
                    const isBest = globalRank === 0 && run.status === "completed";
                    return (
                      <tr
                        key={i}
                        className={`border-b last:border-0 ${isBest ? "bg-green-500/5" : "hover:bg-muted/30"}`}
                      >
                        <td className="px-3 py-2 text-muted-foreground">
                          {isBest ? <Trophy className="h-3 w-3 text-green-500 inline" /> : globalRank + 1}
                        </td>
                        {paramNames.map((p) => (
                          <td key={p} className="px-3 py-2 font-mono">
                            {String(r.params[p] ?? "—")}
                          </td>
                        ))}
                        {ALL_METRICS.map((m) => (
                          <MetricCell
                            key={m}
                            metricKey={m}
                            value={r.metrics[m] as number | null}
                            isOptimizeTarget={m === run.optimize_metric}
                            rank={globalRank}
                            allResults={results}
                          />
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* ── Pagination controls ── */}
            {resultsPage && resultsPage.pages > 1 && (
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, resultsPage.total)} of {resultsPage.total}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline" size="sm" className="h-7 w-7 p-0"
                    disabled={page === 1}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="h-3 w-3" />
                  </Button>
                  <span className="px-2">Page {page} / {resultsPage.pages}</span>
                  <Button
                    variant="outline" size="sm" className="h-7 w-7 p-0"
                    disabled={page >= resultsPage.pages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    <ChevronRight className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {run.status === "completed" && !loadingResults && results.length === 0 && (
          <p className="text-sm text-muted-foreground py-8 text-center">
            No valid results — all combinations may have produced zero trades.
          </p>
        )}
      </div>
    </SidebarInset>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "completed") return <Badge className="gap-1 bg-green-500/15 text-green-700 dark:text-green-400 border-green-500/30"><CheckCircle2 className="h-3 w-3" />Completed</Badge>;
  if (status === "failed") return <Badge variant="destructive" className="gap-1"><XCircle className="h-3 w-3" />Failed</Badge>;
  if (status === "running") return <Badge className="gap-1 bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30"><Loader2 className="h-3 w-3 animate-spin" />Running</Badge>;
  return <Badge variant="outline" className="gap-1"><Clock className="h-3 w-3" />Pending</Badge>;
}

function MetricCell({
  metricKey,
  value,
  isOptimizeTarget,
  rank,
  allResults,
}: {
  metricKey: string;
  value: number | null;
  isOptimizeTarget: boolean;
  rank: number;
  allResults: OptimizationResult[];
}) {
  const lowerIsBetter = metricKey === "max_drawdown_pct";
  const bestRank = 0;
  const isTop = rank === bestRank;

  return (
    <td
      className={`px-3 py-2 text-right font-mono tabular-nums ${
        isOptimizeTarget && isTop
          ? "text-green-600 dark:text-green-400 font-semibold"
          : isOptimizeTarget
          ? "text-foreground"
          : "text-muted-foreground"
      }`}
    >
      {fmt(value, metricKey)}
    </td>
  );
}
