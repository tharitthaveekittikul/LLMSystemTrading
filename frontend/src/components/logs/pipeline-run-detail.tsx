"use client";

import { useEffect, useRef, useState } from "react";
import { formatDateTime } from "@/lib/date";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineStepCard } from "./pipeline-step-card";
import { logsApi } from "@/lib/api";
import type { PipelineRunDetail, PipelineRunSummary, PipelineStep, LLMPricingEntry } from "@/types/trading";

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
  const prevIsLiveRef = useRef(isLiveRun);

  useEffect(() => {
    const wasLive = prevIsLiveRef.current;
    prevIsLiveRef.current = isLiveRun;

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, isLiveRun]);

  const displaySteps: PipelineStep[] = isLiveRun ? liveSteps : (detail?.steps ?? []);
  const ts = formatDateTime(run.created_at);

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
        </div>
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
          displaySteps.map((step) => (
            <PipelineStepCard key={step.id} step={step} pricing={pricing} usdThbRate={usdThbRate} />
          ))
        ) : isLiveRun ? (
          <p className="text-sm text-muted-foreground animate-pulse">Waiting for first step…</p>
        ) : (
          <p className="text-sm text-muted-foreground">Failed to load steps.</p>
        )}
      </div>
    </div>
  );
}
