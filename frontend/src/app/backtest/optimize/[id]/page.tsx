"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { optimizationApi } from "@/lib/api";
import type { OptimizationRunSummary, OptimizationResult, OptimizationResultsPage } from "@/types/trading";
import {
  ArrowLeft,
  Loader2,
  Trophy,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  CalendarRange,
  Cpu,
  Settings2,
  Square,
  Play,
} from "lucide-react";
import { StatusBadge, QualityBadge, MetricCell } from "@/components/backtest/optimize-badges";
import {
  PAGE_SIZE,
  METRIC_LABELS,
  qualityScore,
  ALL_METRICS,
  fmtEta,
  fmtElapsed,
  fmtDate,
  dataDays,
} from "@/lib/optimize-result-utils";

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
  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await optimizationApi.get(Number(id));
      setRun(data);
      if (!sortKey) setSortKey(data.optimize_metric);
    } catch { /* ignore */ }
  }, [id, sortKey]);

  const handleStop = useCallback(async () => {
    setStopping(true);
    try {
      await optimizationApi.cancel(Number(id));
      await refresh();
    } catch { /* ignore */ } finally {
      setStopping(false);
    }
  }, [id, refresh]);

  const handleResume = useCallback(async () => {
    setResuming(true);
    try {
      await optimizationApi.resume(Number(id));
      await refresh();
    } catch { /* ignore */ } finally {
      setResuming(false);
    }
  }, [id, refresh]);

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

  // Load results when run is completed/cancelled or when sort/page changes
  useEffect(() => {
    if ((run?.status === "completed" || run?.status === "cancelled") && sortKey) {
      void loadResults(page, sortKey, sortDesc);
    }
  }, [run?.status, page, sortKey, sortDesc, loadResults]);

  // Poll while pending, running, or cancelling
  useEffect(() => {
    if (!run || !["pending", "running", "cancelling"].includes(run.status)) return;
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
          {(run.status === "pending" || run.status === "running" || run.status === "cancelling") && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>{run.completed_combinations}/{run.total_combinations} combos</span>
              <div className="w-32 bg-muted rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all"
                  style={{ width: `${run.progress_pct}%` }}
                />
              </div>
              <span>{run.progress_pct}%</span>
              {run.estimated_seconds_remaining != null && run.estimated_seconds_remaining > 0 && run.status !== "cancelling" && (
                <span className="text-xs text-muted-foreground">
                  ~{fmtEta(run.estimated_seconds_remaining)} left
                </span>
              )}
              <span className="text-xs text-muted-foreground">({run.max_workers}w)</span>
              {run.status === "running" && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 text-xs border-destructive/50 text-destructive hover:bg-destructive/10"
                  onClick={handleStop}
                  disabled={stopping}
                >
                  {stopping ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3 fill-current" />}
                  Stop
                </Button>
              )}
            </div>
          )}
          {(run.status === "completed" || run.status === "cancelled") && (
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {resultsPage?.total ?? "…"} results{run.status === "cancelled" ? ` (partial — ${run.completed_combinations}/${run.total_combinations} combos run)` : ""} · sorted by {METRIC_LABELS[run.optimize_metric] ?? run.optimize_metric}
              </span>
              {run.status === "cancelled" && run.completed_combinations < run.total_combinations && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 text-xs"
                  onClick={handleResume}
                  disabled={resuming}
                >
                  {resuming ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3 fill-current" />}
                  Resume
                </Button>
              )}
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

        {run.skip_llm === false && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            ⚠️ LLM calls were enabled for this optimization run — API cost was incurred per combination.
            Use rule-only mode (skip LLM) for future sweeps.
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
