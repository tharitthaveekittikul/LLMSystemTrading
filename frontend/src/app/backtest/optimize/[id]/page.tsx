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
  Filter,
  ShieldCheck,
  CalendarRange,
  Cpu,
  Settings2,
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

// ── Quality thresholds ("Good" tier) ──────────────────────────────────────
const THRESHOLDS: Record<string, { value: number; lowerIsBetter: boolean; label: string }> = {
  sharpe_ratio:     { value: 1.5,  lowerIsBetter: false, label: "Sharpe ≥ 1.5"   },
  profit_factor:    { value: 1.75, lowerIsBetter: false, label: "PF ≥ 1.75"       },
  win_rate:         { value: 0.55, lowerIsBetter: false, label: "Win ≥ 55%"       },
  max_drawdown_pct: { value: 20,   lowerIsBetter: true,  label: "MDD ≤ 20%"       },
  recovery_factor:  { value: 2.0,  lowerIsBetter: false, label: "RF ≥ 2.0"        },
  total_return_pct: { value: 10,   lowerIsBetter: false, label: "Return ≥ 10%"    },
  total_trades:     { value: 20,   lowerIsBetter: false, label: "Trades ≥ 20"     },
};

function qualityScore(metrics: { [key: string]: number | null }): { passed: number; total: number; allPassed: boolean } {
  let passed = 0;
  const total = Object.keys(THRESHOLDS).length;
  for (const [key, t] of Object.entries(THRESHOLDS)) {
    const v = metrics[key];
    if (v == null) continue;
    if (t.lowerIsBetter ? v <= t.value : v >= t.value) passed++;
  }
  return { passed, total, allPassed: passed === total };
}

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

function fmtElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (seconds < 3600) return `${m}m ${s}s`;
  const h = Math.floor(seconds / 3600);
  const rem = Math.floor((seconds % 3600) / 60);
  return `${h}h ${rem}m`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function dataDays(start: string, end: string): number {
  return Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86_400_000);
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
  const [showQualifiedOnly, setShowQualifiedOnly] = useState(false);

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
  const filteredResults = showQualifiedOnly
    ? results.filter((r) => qualityScore(r.metrics).allPassed)
    : results;
  const qualifiedCount = results.filter((r) => qualityScore(r.metrics).allPassed).length;

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
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {resultsPage?.total ?? "…"} results · sorted by {METRIC_LABELS[run.optimize_metric] ?? run.optimize_metric}
              </span>
              <Button
                variant={showQualifiedOnly ? "default" : "outline"}
                size="sm"
                className="h-7 gap-1.5 text-xs"
                onClick={() => setShowQualifiedOnly((v) => !v)}
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                Qualified only
                {qualifiedCount > 0 && (
                  <span className={`rounded-full px-1.5 py-0 text-[10px] font-semibold ${showQualifiedOnly ? "bg-white/20 text-white" : "bg-green-500/15 text-green-700 dark:text-green-400"}`}>
                    {qualifiedCount}
                  </span>
                )}
              </Button>
            </div>
          )}
        </div>

        {/* ── Run Config panel ── */}
        <div className="grid grid-cols-3 gap-3 text-xs">
          {/* Data Period */}
          <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-muted-foreground uppercase tracking-wide text-[10px]">
              <CalendarRange className="h-3.5 w-3.5" />
              Data Period
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">From</span>
                <span className="font-mono">{fmtDate(run.start_date)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">To</span>
                <span className="font-mono">{fmtDate(run.end_date)}</span>
              </div>
              <div className="flex justify-between border-t pt-1 mt-1">
                <span className="text-muted-foreground">Duration</span>
                <span className="font-semibold">{dataDays(run.start_date, run.end_date)} days</span>
              </div>
            </div>
          </div>

          {/* Trade Assumptions */}
          <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-muted-foreground uppercase tracking-wide text-[10px]">
              <Settings2 className="h-3.5 w-3.5" />
              Trade Assumptions
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Balance</span>
                <span className="font-mono">${run.initial_balance.toLocaleString()}</span>
              </div>
              {run.risk_pct != null ? (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Risk/trade</span>
                  <span className="font-mono">{(run.risk_pct * 100).toFixed(1)}%</span>
                </div>
              ) : (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Volume</span>
                  <span className="font-mono">{run.volume} lot</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted-foreground">Spread</span>
                <span className="font-mono">{run.spread_pips} pips</span>
              </div>
              {run.commission_per_lot > 0 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Commission</span>
                  <span className="font-mono">${run.commission_per_lot}/lot</span>
                </div>
              )}
              <div className="flex justify-between border-t pt-1 mt-1">
                <span className="text-muted-foreground">Execution</span>
                <span className="font-semibold">{run.execution_mode === "close_price" ? "Close price" : "Intra-candle"}</span>
              </div>
            </div>
          </div>

          {/* Run Info */}
          <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-muted-foreground uppercase tracking-wide text-[10px]">
              <Cpu className="h-3.5 w-3.5" />
              Run Info
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Workers</span>
                <span className="font-mono">{run.max_workers}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Combinations</span>
                <span className="font-mono">{run.total_combinations}</span>
              </div>
              {run.elapsed_seconds != null && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Elapsed</span>
                  <span className="font-mono">{fmtElapsed(run.elapsed_seconds)}</span>
                </div>
              )}
              {run.elapsed_seconds != null && run.completed_combinations > 0 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Avg speed</span>
                  <span className="font-mono">
                    ~{(run.elapsed_seconds / run.completed_combinations).toFixed(2)}s/combo
                  </span>
                </div>
              )}
              <div className="flex justify-between border-t pt-1 mt-1">
                <span className="text-muted-foreground">Optimize for</span>
                <span className="font-semibold">{METRIC_LABELS[run.optimize_metric] ?? run.optimize_metric}</span>
              </div>
            </div>
          </div>
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
        {(filteredResults.length > 0 || loadingResults) && (
          <div className="space-y-2">
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-muted/50 border-b">
                    <th className="text-left px-3 py-2 font-medium text-muted-foreground">#</th>
                    <th className="text-center px-3 py-2 font-medium text-muted-foreground whitespace-nowrap">Qual</th>
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
                    <th className="text-right px-3 py-2 font-medium text-muted-foreground whitespace-nowrap">
                      Net Profit
                    </th>
                    <th className="text-right px-3 py-2 font-medium text-muted-foreground whitespace-nowrap">
                      Final Balance
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {loadingResults ? (
                    <tr>
                      <td colSpan={paramNames.length + ALL_METRICS.length + 4} className="text-center py-6 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Loading…
                      </td>
                    </tr>
                  ) : filteredResults.map((r, i) => {
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
                        <td className="px-3 py-2 text-center">
                          <QualityBadge metrics={r.metrics} />
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
                        <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
                          {r.metrics.total_return_pct != null
                            ? `$${(run.initial_balance * r.metrics.total_return_pct / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono tabular-nums font-semibold">
                          {r.metrics.total_return_pct != null
                            ? `$${(run.initial_balance * (1 + r.metrics.total_return_pct / 100)).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                            : "—"}
                        </td>
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
        {run.status === "completed" && !loadingResults && results.length > 0 && filteredResults.length === 0 && (
          <p className="text-sm text-muted-foreground py-8 text-center">
            No combinations passed all quality thresholds on this page. Try turning off the filter or going to the next page.
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

function QualityBadge({ metrics }: { metrics: { [key: string]: number | null } }) {
  const { passed, total, allPassed } = qualityScore(metrics);
  const failedLabels = Object.entries(THRESHOLDS)
    .filter(([key, t]) => {
      const v = metrics[key];
      if (v == null) return false;
      return t.lowerIsBetter ? v > t.value : v < t.value;
    })
    .map(([, t]) => t.label);

  if (allPassed) {
    return (
      <span title={`All ${total} criteria passed`} className="inline-flex items-center gap-1 text-green-600 dark:text-green-400 font-semibold text-xs">
        <ShieldCheck className="h-3.5 w-3.5" />
        {passed}/{total}
      </span>
    );
  }
  return (
    <span title={`Failed: ${failedLabels.join(", ")}`} className={`inline-flex items-center gap-1 text-xs font-mono ${passed >= total - 1 ? "text-yellow-600 dark:text-yellow-400" : "text-muted-foreground"}`}>
      <Filter className="h-3 w-3" />
      {passed}/{total}
    </span>
  );
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
