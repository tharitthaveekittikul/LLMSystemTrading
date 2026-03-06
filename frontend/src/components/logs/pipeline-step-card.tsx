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
  account_loaded:          "Account Loaded",
  rate_limit_check:        "Rate Limit Check",
  ohlcv_fetch:             "OHLCV Fetch",
  indicators_computed:     "Indicators Computed",
  hmm_regime:              "HMM Regime Detection",
  positions_fetched:       "Positions Fetched",
  signals_fetched:         "Recent Signals Fetched",
  rule_signal:             "Rule-Based Signal",
  market_analysis_llm:     "Market Analysis (LLM)",
  chart_vision_llm:        "Chart Vision (LLM)",
  execution_decision_llm:  "Execution Decision (LLM)",
  llm_analyzed:            "LLM Analysis (legacy)",
  confidence_gate:         "Confidence Gate",
  regime_gate:             "Regime Gate",
  lot_size_calculated:     "Lot Size Calculated",
  journal_saved:           "Journal Saved",
  kill_switch_check:       "Kill Switch Check",
  order_built:             "Order Built",
  mt5_executed:            "MT5 Order Executed",
  telegram_sent:           "Telegram Alert Sent",
}

const LLM_STEP_NAMES = new Set([
  "market_analysis_llm",
  "chart_vision_llm",
  "execution_decision_llm",
  "llm_analyzed",
])

interface TokenInfo {
  model: string
  provider: string
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
}

function extractTokenInfo(step: PipelineStep): TokenInfo | null {
  if (!LLM_STEP_NAMES.has(step.step_name) || !step.output_json) return null
  try {
    const out = JSON.parse(step.output_json)
    if (!out.model && out.input_tokens == null) return null
    return {
      model:         out.model         ?? "unknown",
      provider:      out.provider      ?? "unknown",
      input_tokens:  out.input_tokens  ?? null,
      output_tokens: out.output_tokens ?? null,
      total_tokens:  out.total_tokens  ?? null,
    }
  } catch {
    return null
  }
}

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
  const [expanded, setExpanded] = useState(false)
  const hasDetail = step.input_json || step.output_json || step.error
  const label = STEP_LABELS[step.step_name] ?? step.step_name
  const tokenInfo = extractTokenInfo(step)

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

      {tokenInfo && (
        <div className="mt-1 ml-6 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono bg-muted/60 px-1.5 py-0.5 rounded">
            {tokenInfo.provider}/{tokenInfo.model}
          </span>
          {tokenInfo.input_tokens != null && (
            <>
              <span>↑ {tokenInfo.input_tokens.toLocaleString()} in</span>
              <span>↓ {(tokenInfo.output_tokens ?? 0).toLocaleString()} out</span>
              <span className="font-medium">∑ {(tokenInfo.total_tokens ?? 0).toLocaleString()} total</span>
            </>
          )}
        </div>
      )}

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
  )
}
