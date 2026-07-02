"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { formatDateTime } from "@/lib/date";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineStepCard } from "./pipeline-step-card";
import { logsApi } from "@/lib/api";
import type { PipelineRunDetail, PipelineRunSummary, PipelineStep, LLMPricingEntry } from "@/types/trading";

/** True if the run outright failed, or any step errored, or a step's output
 * silently carries a "pipeline_error:" justification (caught internally and
 * downgraded to HOLD rather than raising). */
function hasFailure(run: PipelineRunSummary, steps: PipelineStep[]): boolean {
  if (run.status === "failed") return true;
  return steps.some((s) => {
    if (s.status === "error") return true;
    if (!s.output_json) return false;
    return s.output_json.includes("pipeline_error");
  });
}

const STATUS_VARIANT: Record<string, string> = {
  completed: "bg-green-500/15 text-green-700 dark:text-green-400",
  hold: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  skipped: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-400 animate-pulse",
};

const ACTION_VARIANT: Record<string, string> = {
  BUY: "bg-green-500/15 text-green-700 dark:text-green-400",
  SELL: "bg-red-500/15 text-red-700 dark:text-red-400",
  HOLD: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
};

interface PipelineRunDetailPanelProps {
  run: PipelineRunSummary;
  pricing?: LLMPricingEntry[];
  usdThbRate?: number;
  liveSteps?: PipelineStep[];
  isLiveRun?: boolean;
}

export function PipelineRunDetailPanel({
  run,
  pricing = [],
  usdThbRate = 36.0,
  liveSteps = [],
  isLiveRun = false,
}: PipelineRunDetailPanelProps) {
  const [detail, setDetail] = useState<PipelineRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  useEffect(() => {
    if (isLiveRun) {
      // Run is in-progress — don't fetch from DB yet
      setLoading(false);
      return;
    }

    // Fetch from DB: either a historical run was selected, or a live run just completed
    setLoading(true);
    setDetail(null);
    (async () => {
      try {
        const data = await logsApi.getRun(run.id);
        setDetail(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    })();
  // Re-run when run.id changes OR when isLiveRun flips from true→false (run completed)
   
  }, [run.id, isLiveRun]);

  const displaySteps: PipelineStep[] = isLiveRun ? liveSteps : (detail?.steps ?? []);
  const ts = formatDateTime(run.created_at);
  const canRetry =
    !isLiveRun && run.task_type !== "maintenance" && hasFailure(run, displaySteps);

  const handleRetry = async () => {
    setRetrying(true);
    setRetryError(null);
    try {
      await logsApi.retryRun(run.id);
      // The new run appears as a "running" entry in the runs list via the
      // pipeline_run_started WS event — select it there to watch it live.
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-sm">
            Run #{run.id} — {run.symbol} {run.timeframe}
          </span>
          <Badge
            variant="outline"
            className={`text-xs ${STATUS_VARIANT[isLiveRun ? "running" : run.status] ?? ""}`}
          >
            {isLiveRun ? "running" : run.status}
          </Badge>
          {isLiveRun && (
            <span className="flex items-center gap-1 text-xs text-blue-500">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-ping" />
              live
            </span>
          )}
          {run.final_action && !isLiveRun && (
            <Badge
              variant="outline"
              className={`text-xs ${ACTION_VARIANT[run.final_action] ?? ""}`}
            >
              {run.final_action}
            </Badge>
          )}
          {canRetry && (
            <Button
              variant="outline"
              size="xs"
              onClick={handleRetry}
              disabled={retrying}
              className="ml-auto"
            >
              <RefreshCw className={`h-3 w-3 ${retrying ? "animate-spin" : ""}`} />
              {retrying ? "Retrying…" : "Retry"}
            </Button>
          )}
        </div>
        {retryError && (
          <p className="text-xs text-red-600 dark:text-red-400">
            Retry failed: {retryError}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {ts}
          {!isLiveRun && run.total_duration_ms != null &&
            ` · ${run.total_duration_ms}ms total`}
          {run.trade_id && ` · Trade #${run.trade_id}`}
          {isLiveRun && displaySteps.length > 0 &&
            ` · ${displaySteps.length} step${displaySteps.length !== 1 ? "s" : ""} so far`}
        </p>
      </div>

      {/* Steps */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {loading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))
        ) : displaySteps.length > 0 ? (
          <>
            {displaySteps.map((step) => (
              <PipelineStepCard
                key={step.id}
                step={step}
                pricing={pricing}
                usdThbRate={usdThbRate}
                onRetry={canRetry ? handleRetry : undefined}
                retrying={retrying}
              />
            ))}
            {isLiveRun && (
              <div className="border-l-2 border-muted pl-4 py-1 flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-blue-500 animate-ping shrink-0" />
                <span className="text-xs text-muted-foreground animate-pulse">Running next step…</span>
              </div>
            )}
          </>
        ) : isLiveRun ? (
          <p className="text-sm text-muted-foreground animate-pulse">Waiting for first step…</p>
        ) : (
          <p className="text-sm text-muted-foreground">Failed to load steps.</p>
        )}
      </div>
    </div>
  );
}
