"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { optimizationApi, API_BASE_URL } from "@/lib/api";
import type { OptimizationRunSummary } from "@/types/trading";
import { Plus, FlaskConical, Clock, CheckCircle2, XCircle, Loader2 } from "lucide-react";

export default function OptimizePage() {
  const router = useRouter();
  const [runs, setRuns] = useState<OptimizationRunSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await optimizationApi.list({ limit: 50 });
      setRuns(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // Poll while any run is active
  useEffect(() => {
    const hasActive = runs.some((r) => r.status === "pending" || r.status === "running");
    if (!hasActive) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [runs, refresh]);

  return (
    <SidebarInset>
      <AppHeader
        title="Optimize"
        subtitle="Parameter sweep — find the best strategy config"
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Run multiple parameter combinations at once and rank by your chosen metric.
          </p>
          <Button
            size="sm"
            className="gap-1.5"
            onClick={() => router.push("/backtest/optimize/new")}
          >
            <Plus className="h-4 w-4" />
            New Optimization
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        ) : runs.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
            <FlaskConical className="h-10 w-10 opacity-30" />
            <p className="text-sm font-medium">No optimization runs yet</p>
            <p className="text-xs">Click &ldquo;New Optimization&rdquo; to sweep strategy parameters.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <OptimizationRunCard
                key={run.id}
                run={run}
                onClick={() => router.push(`/backtest/optimize/${run.id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </SidebarInset>
  );
}

function OptimizationRunCard({
  run,
  onClick,
}: {
  run: OptimizationRunSummary;
  onClick: () => void;
}) {
  const paramNames = Object.keys(run.param_grid);
  const best = run.best_params;

  return (
    <button
      onClick={onClick}
      className="w-full text-left border rounded-lg p-3 hover:bg-accent transition-colors space-y-1.5"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusIcon status={run.status} />
          <span className="text-sm font-medium">
            #{run.id} — {run.symbol} · {run.timeframe}
          </span>
          <Badge variant="outline" className="text-xs">
            {run.optimize_metric.replace(/_/g, " ")}
          </Badge>
        </div>
        <span className="text-xs text-muted-foreground">
          {new Date(run.created_at).toLocaleDateString()}
        </span>
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>Params: {paramNames.join(", ")}</span>
        <span>·</span>
        <span>{run.completed_combinations}/{run.total_combinations} combos</span>
        {run.status === "running" && (
          <>
            <span>·</span>
            <span>{run.progress_pct}%</span>
          </>
        )}
      </div>

      {run.status === "completed" && best && Object.keys(best).length > 0 && (
        <div className="text-xs text-green-600 dark:text-green-400">
          Best: {Object.entries(best).map(([k, v]) => `${k}=${v}`).join(", ")}
        </div>
      )}

      {run.status === "running" && (
        <div className="w-full bg-muted rounded-full h-1">
          <div
            className="bg-primary h-1 rounded-full transition-all"
            style={{ width: `${run.progress_pct}%` }}
          />
        </div>
      )}
    </button>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-green-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-destructive" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
  return <Clock className="h-4 w-4 text-muted-foreground" />;
}
