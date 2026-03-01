"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineStepCard } from "./pipeline-step-card";
import { logsApi } from "@/lib/api";
import type { PipelineRunDetail, PipelineRunSummary } from "@/types/trading";

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
}

export function PipelineRunDetailPanel({ run }: PipelineRunDetailPanelProps) {
  const [detail, setDetail] = useState<PipelineRunDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    logsApi
      .getRun(run.id)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [run.id]);

  const ts = new Date(run.created_at).toLocaleString();

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
            className={`text-xs ${STATUS_VARIANT[run.status] ?? ""}`}
          >
            {run.status}
          </Badge>
          {run.final_action && (
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
          {run.total_duration_ms != null && ` · ${run.total_duration_ms}ms total`}
          {run.trade_id && ` · Trade #${run.trade_id}`}
        </p>
      </div>

      {/* Steps */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {loading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))
        ) : detail ? (
          detail.steps.map((step) => (
            <PipelineStepCard key={step.id} step={step} />
          ))
        ) : (
          <p className="text-sm text-muted-foreground">Failed to load steps.</p>
        )}
      </div>
    </div>
  );
}
