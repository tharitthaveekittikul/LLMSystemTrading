"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { PipelineStep } from "@/types/trading";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-green-500/15 text-green-700 dark:text-green-400",
  skip: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  error: "bg-red-500/15 text-red-700 dark:text-red-400",
};

const STEP_LABELS: Record<string, string> = {
  account_loaded: "Account Loaded",
  rate_limit_check: "Rate Limit Check",
  ohlcv_fetch: "OHLCV Fetch",
  indicators_computed: "Indicators Computed",
  positions_fetched: "Positions Fetched",
  signals_fetched: "Recent Signals Fetched",
  llm_analyzed: "LLM Analysis",
  confidence_gate: "Confidence Gate",
  journal_saved: "Journal Saved",
  kill_switch_check: "Kill Switch Check",
  order_built: "Order Built",
  mt5_executed: "MT5 Order Executed",
  telegram_sent: "Telegram Alert Sent",
};

interface PipelineStepCardProps {
  step: PipelineStep;
}

function JsonViewer({ raw }: { raw: string | null }) {
  if (!raw) return <span className="text-muted-foreground text-xs">—</span>;
  try {
    const parsed = JSON.parse(raw);
    return (
      <pre className="text-xs bg-muted/50 rounded p-2 overflow-auto max-h-48 whitespace-pre-wrap break-all">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    );
  } catch {
    return <pre className="text-xs text-muted-foreground">{raw}</pre>;
  }
}

export function PipelineStepCard({ step }: PipelineStepCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = step.input_json || step.output_json || step.error;
  const label = STEP_LABELS[step.step_name] ?? step.step_name;

  return (
    <div className="border-l-2 border-muted pl-4 py-1">
      <button
        className="flex items-center gap-2 w-full text-left group"
        onClick={() => hasDetail && setExpanded((v) => !v)}
        disabled={!hasDetail}
      >
        <span className="text-muted-foreground text-xs w-4 shrink-0">
          {step.seq}.
        </span>
        <span className="flex-1 text-sm font-medium">{label}</span>
        <Badge
          className={`text-xs shrink-0 ${STATUS_STYLES[step.status] ?? ""}`}
          variant="outline"
        >
          {step.status}
        </Badge>
        <span className="text-xs text-muted-foreground w-16 text-right shrink-0">
          {step.duration_ms}ms
        </span>
        {hasDetail && (
          <span className="text-muted-foreground shrink-0">
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </span>
        )}
      </button>

      {expanded && hasDetail && (
        <div className="mt-2 space-y-2">
          {step.error && (
            <div>
              <p className="text-xs font-semibold text-red-600 mb-1">Error</p>
              <pre className="text-xs bg-red-50 dark:bg-red-950/20 rounded p-2 text-red-700 dark:text-red-400 whitespace-pre-wrap">
                {step.error}
              </pre>
            </div>
          )}
          {step.input_json && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Input</p>
              <JsonViewer raw={step.input_json} />
            </div>
          )}
          {step.output_json && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Output</p>
              <JsonViewer raw={step.output_json} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
