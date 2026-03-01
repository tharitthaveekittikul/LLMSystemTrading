"use client";

import { useCallback, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/use-websocket";
import { useTradingStore } from "@/hooks/use-trading-store";
import { PipelineRunsList } from "@/components/logs/pipeline-runs-list";
import { PipelineRunDetailPanel } from "@/components/logs/pipeline-run-detail";
import type {
  PipelineRunCompleteData,
  PipelineRunSummary,
} from "@/types/trading";

export default function LogsPage() {
  const { activeAccountId } = useTradingStore();
  const [selectedRun, setSelectedRun] = useState<PipelineRunSummary | null>(null);
  const newRunHandlerRef = useRef<((data: PipelineRunCompleteData) => void) | null>(null);

  const registerNewRunHandler = useCallback(
    (handler: (data: PipelineRunCompleteData) => void) => {
      newRunHandlerRef.current = handler;
    },
    []
  );

  useWebSocket(activeAccountId, {
    pipeline_run_complete: (data) => {
      newRunHandlerRef.current?.(data as PipelineRunCompleteData);
    },
  });

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Left — runs list */}
      <div className="w-72 shrink-0 border-r flex flex-col">
        <div className="p-3 border-b">
          <h2 className="font-semibold text-sm">Pipeline Logs</h2>
          <p className="text-xs text-muted-foreground">
            Every AI analysis run, step by step
          </p>
        </div>
        <PipelineRunsList
          selectedRunId={selectedRun?.id ?? null}
          onSelect={setSelectedRun}
          onNewRun={registerNewRunHandler}
        />
      </div>

      {/* Right — detail */}
      <div className="flex-1 overflow-hidden">
        {selectedRun ? (
          <PipelineRunDetailPanel run={selectedRun} />
        ) : (
          <div className="h-full flex items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Select a run from the list to see its step trace.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
