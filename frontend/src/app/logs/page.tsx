"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import { useWebSocket } from "@/hooks/use-websocket";
import { useTradingStore } from "@/hooks/use-trading-store";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { PipelineRunsList } from "@/components/logs/pipeline-runs-list";
import { PipelineRunDetailPanel } from "@/components/logs/pipeline-run-detail";
import { llmUsageApi } from "@/lib/api";
import type {
  PipelineRunCompleteData,
  PipelineRunStartedData,
  PipelineStep,
  PipelineStepData,
  PipelineRunSummary,
  LLMPricingEntry,
} from "@/types/trading";

export default function LogsPage() {
  const { activeAccountId } = useTradingStore();
  const [selectedRun, setSelectedRun] = useState<PipelineRunSummary | null>(null);

  // Live pipeline tracking
  const liveRunIdRef = useRef<number | null>(null);
  const [liveRunId, setLiveRunId] = useState<number | null>(null);
  const [liveSteps, setLiveSteps] = useState<PipelineStep[]>([]);

  // Callbacks registered by child list component
  const newRunHandlerRef = useRef<((data: PipelineRunCompleteData) => void) | null>(null);
  const runStartedHandlerRef = useRef<((data: PipelineRunStartedData) => void) | null>(null);

  const [pricing, setPricing] = useState<LLMPricingEntry[]>([]);
  const [usdThbRate, setUsdThbRate] = useState<number>(36.0);

  useEffect(() => {
    Promise.all([
      llmUsageApi.getPricing().catch(() => []),
      llmUsageApi.getSummary("day").catch(() => null),
    ]).then(([pricingData, summaryData]) => {
      setPricing(pricingData);
      if (summaryData?.usd_thb_rate) {
        setUsdThbRate(summaryData.usd_thb_rate);
      }
    });
  }, []);

  const registerNewRunHandler = useCallback(
    (handler: (data: PipelineRunCompleteData) => void) => {
      newRunHandlerRef.current = handler;
    },
    [],
  );

  const registerRunStartedHandler = useCallback(
    (handler: (data: PipelineRunStartedData) => void) => {
      runStartedHandlerRef.current = handler;
    },
    [],
  );

  useWebSocket(activeAccountId, {
    pipeline_run_started: (data) => {
      const d = data as PipelineRunStartedData;
      liveRunIdRef.current = d.run_id;
      setLiveRunId(d.run_id);
      setLiveSteps([]);
      runStartedHandlerRef.current?.(d);
    },
    pipeline_step: (data) => {
      const d = data as PipelineStepData;
      if (liveRunIdRef.current === d.run_id) {
        setLiveSteps((prev) => [
          ...prev,
          {
            id: d.id,
            run_id: d.run_id,
            seq: d.seq,
            step_name: d.step_name,
            status: d.status,
            input_json: d.input_json,
            output_json: d.output_json,
            error: d.error,
            duration_ms: d.duration_ms,
          },
        ]);
      }
    },
    pipeline_run_complete: (data) => {
      const d = data as PipelineRunCompleteData;
      if (liveRunIdRef.current === d.run_id) {
        liveRunIdRef.current = null;
        setLiveRunId(null);
      }
      newRunHandlerRef.current?.(d);
    },
  });

  const isLiveRun = selectedRun?.id === liveRunId;

  return (
    <SidebarInset>
      <AppHeader
        title="Pipeline Logs"
        subtitle="Every AI analysis run, step by step"
        showAccountSelector={true}
        showConnectionStatus={false}
      />
      <div
        className="flex flex-1 min-h-0 overflow-hidden"
        style={{ height: "calc(100vh - 3rem)" }}
      >
        {/* Left — runs list */}
        <div className="w-72 shrink-0 border-r flex flex-col">
          <PipelineRunsList
            selectedRunId={selectedRun?.id ?? null}
            onSelect={setSelectedRun}
            onNewRun={registerNewRunHandler}
            onRunStarted={registerRunStartedHandler}
          />
        </div>

        {/* Right — detail */}
        <div className="flex-1 overflow-hidden">
          {selectedRun ? (
            <PipelineRunDetailPanel
              run={selectedRun}
              pricing={pricing}
              usdThbRate={usdThbRate}
              liveSteps={isLiveRun ? liveSteps : []}
              isLiveRun={isLiveRun}
            />
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-sm text-muted-foreground">
                Select a run from the list to see its step trace.
              </p>
            </div>
          )}
        </div>
      </div>
    </SidebarInset>
  );
}
