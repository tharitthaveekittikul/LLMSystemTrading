"use client";

import { cn } from "@/lib/utils";
import type { BacktestRunSummary } from "@/types/trading";

interface Props {
  runs: BacktestRunSummary[];
  selectedRunId: number | null;
  onSelect: (run: BacktestRunSummary) => void;
}

const STATUS_STYLE: Record<string, string> = {
  pending:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
  running:
    "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  completed:
    "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
};

export function BacktestRunList({ runs, selectedRunId, onSelect }: Props) {
  if (runs.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-4">
        No runs yet — configure and submit above.
      </p>
    );
  }

  return (
    <ul className="space-y-1">
      {runs.map((run) => (
        <li key={run.id}>
          <button
            onClick={() => onSelect(run)}
            className={cn(
              "w-full text-left rounded-md px-2.5 py-2 text-xs hover:bg-accent transition-colors",
              selectedRunId === run.id && "bg-accent",
            )}
          >
            <div className="flex items-center justify-between gap-1.5">
              <span className="font-medium truncate">
                {run.symbol} · {run.timeframe}
              </span>
              <span
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0",
                  STATUS_STYLE[run.status],
                )}
              >
                {run.status}
              </span>
            </div>
            <div className="text-muted-foreground mt-0.5">
              {run.start_date.slice(0, 10)} → {run.end_date.slice(0, 10)}
            </div>
            {run.status === "running" && (
              <div className="mt-1 h-1 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${run.progress_pct}%` }}
                />
              </div>
            )}
            {run.status === "completed" && run.total_return_pct != null && (
              <span
                className={cn(
                  "font-medium",
                  run.total_return_pct >= 0 ? "text-green-600" : "text-red-500",
                )}
              >
                {run.total_return_pct >= 0 ? "+" : ""}
                {run.total_return_pct.toFixed(2)}%
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
