"use client";

import { useCallback, useEffect, useState } from "react";
import { formatDateTime } from "@/lib/date";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { logsApi } from "@/lib/api";
import { useTradingStore } from "@/hooks/use-trading-store";
import type {
  PipelineRunCompleteData,
  PipelineRunSummary,
} from "@/types/trading";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-green-500/15 text-green-700 dark:text-green-400",
  hold: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  skipped: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400",
  running: "bg-blue-500/15 text-blue-600 dark:text-blue-400 animate-pulse",
};

const ACTION_DOT: Record<string, string> = {
  BUY: "bg-green-500",
  SELL: "bg-red-500",
  HOLD: "bg-yellow-500",
};

interface PipelineRunsListProps {
  selectedRunId: number | null;
  onSelect: (run: PipelineRunSummary) => void;
  onNewRun: (handler: (data: PipelineRunCompleteData) => void) => void;
}

export function PipelineRunsList({
  selectedRunId,
  onSelect,
  onNewRun,
}: PipelineRunsListProps) {
  const { activeAccountId } = useTradingStore();
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [newRunIds, setNewRunIds] = useState<Set<number>>(new Set());

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await logsApi.listRuns({
        account_id: activeAccountId ?? undefined,
        symbol: symbolFilter.trim() || undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        limit: 100,
      });
      setRuns(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [activeAccountId, symbolFilter, statusFilter]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Register the new-run handler with parent so WS events flow in
  useEffect(() => {
    onNewRun((data: PipelineRunCompleteData) => {
      const newSummary: PipelineRunSummary = {
        id: data.run_id,
        account_id: activeAccountId ?? 0,
        symbol: data.symbol,
        timeframe: data.timeframe,
        status: data.status as PipelineRunSummary["status"],
        final_action: data.final_action as PipelineRunSummary["final_action"],
        total_duration_ms: data.total_duration_ms,
        journal_id: null,
        trade_id: null,
        created_at: new Date().toISOString(),
      };
      setNewRunIds((prev) => new Set(prev).add(data.run_id));
      setRuns((prev) => [newSummary, ...prev.slice(0, 99)]);
      setTimeout(() => {
        setNewRunIds((prev) => {
          const next = new Set(prev);
          next.delete(data.run_id);
          return next;
        });
      }, 3000);
    });
  }, [onNewRun, activeAccountId]);

  return (
    <div className="h-full flex flex-col">
      {/* Filters */}
      <div className="p-3 border-b space-y-2">
        <Input
          placeholder="Filter by symbol (e.g. EURUSD)"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="h-8 text-sm"
        />
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="hold">Hold</SelectItem>
            <SelectItem value="skipped">Skipped</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto divide-y">
        {loading ? (
          Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="p-3">
              <Skeleton className="h-4 w-3/4 mb-1" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))
        ) : runs.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No runs found.</p>
        ) : (
          runs.map((run) => {
            const isNew = newRunIds.has(run.id);
            const isSelected = run.id === selectedRunId;
            return (
              <button
                key={run.id}
                onClick={() => onSelect(run)}
                className={[
                  "w-full text-left px-3 py-2.5 transition-colors",
                  isSelected ? "bg-accent" : "hover:bg-accent/50",
                  isNew ? "bg-primary/5" : "",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  {run.final_action && (
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${ACTION_DOT[run.final_action] ?? "bg-muted"}`}
                    />
                  )}
                  <span className="text-sm font-medium flex-1 truncate">
                    {run.symbol} {run.timeframe}
                  </span>
                  <Badge
                    variant="outline"
                    className={`text-xs shrink-0 ${STATUS_STYLES[run.status] ?? ""}`}
                  >
                    {run.status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 pl-4">
                  #{run.id} · {formatDateTime(run.created_at)}
                  {run.total_duration_ms != null &&
                    ` · ${run.total_duration_ms}ms`}
                </p>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
