"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTradingStore } from "@/hooks/use-trading-store";
import { accountsApi } from "@/lib/api/accounts";
import type { ResearchProgress } from "@/types/trading";

const CYCLE_SIZE = 30;

export function ResearchLoopProgress() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const [progress, setProgress] = useState<ResearchProgress | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  const fetchProgress = useCallback(async () => {
    if (!activeAccountId) return;
    try {
      const data = await accountsApi.getResearchProgress(activeAccountId);
      setProgress(data);
    } catch {
      // keep stale data on error
    }
  }, [activeAccountId]);

  useEffect(() => {
    setProgress(null);
    fetchProgress();
    const id = setInterval(fetchProgress, 30_000);
    return () => clearInterval(id);
  }, [fetchProgress]);

  const handleTrigger = async () => {
    if (!activeAccountId) return;
    setTriggering(true);
    setTriggerError(null);
    try {
      await accountsApi.triggerResearchLoop(activeAccountId);
      await fetchProgress();
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : "Trigger failed");
    } finally {
      setTriggering(false);
    }
  };

  if (!activeAccountId) {
    return (
      <div className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground text-center">
        Select an account to view research loop progress.
      </div>
    );
  }

  const isReady = progress?.just_completed ?? false;
  const pct = progress && !isReady ? (progress.cycle_progress / CYCLE_SIZE) * 100 : isReady ? 100 : 0;

  return (
    <Card className={`border-2 ${isReady ? "border-emerald-500/50 bg-emerald-500/5" : "border-violet-500/30 bg-violet-500/5"}`}>
      <CardHeader className="pb-2 pt-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical className={`h-4 w-4 ${isReady ? "text-emerald-400" : "text-violet-400"}`} />
            <CardTitle className={`text-sm ${isReady ? "text-emerald-300" : "text-violet-300"}`}>
              Research Loop Progress
            </CardTitle>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1.5 text-xs border-violet-500/40 text-violet-300 hover:bg-violet-500/10"
            onClick={handleTrigger}
            disabled={triggering}
          >
            <RefreshCw className={`h-3 w-3 ${triggering ? "animate-spin" : ""}`} />
            {triggering ? "Running…" : "Force Run"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Progress bar */}
        <div className="space-y-1.5">
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${isReady ? "bg-emerald-500" : "bg-violet-500"}`}
              style={{ width: `${pct}%` }}
            />
          </div>

          {progress ? (
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                Progress:{" "}
                <span className="font-semibold text-foreground">
                  {progress.cycle_progress}/{CYCLE_SIZE} Trades Analyzed
                </span>
              </span>
              {isReady ? (
                <span className="font-semibold text-emerald-400">Research Ready</span>
              ) : (
                <span className="text-muted-foreground">
                  <span className="font-semibold text-foreground">{progress.remaining}</span>{" "}
                  trades until next Research Loop
                </span>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Loading…</p>
          )}
        </div>

        {/* Research-ready banner */}
        {isReady && progress?.last_run_at && (
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            Research Loop ran after trade #{progress.closed_trades} —{" "}
            {new Date(progress.last_run_at).toLocaleString()}
          </div>
        )}

        {/* Last-run footnote */}
        {!isReady && progress?.last_run_at && (
          <p className="text-[11px] text-muted-foreground">
            Last loop:{" "}
            <span className="text-foreground">
              {new Date(progress.last_run_at).toLocaleString()}
            </span>
            {" · "}
            {progress.closed_trades} total closed trades
          </p>
        )}

        {triggerError && (
          <p className="text-xs text-destructive">{triggerError}</p>
        )}
      </CardContent>
    </Card>
  );
}
