"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Loader2,
  Terminal,
  Cpu,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api";
import { toBangkok, toBangkokTime, isPast } from "@/lib/news-time";
import type { EconomicEvent } from "@/types/trading";

const IMPACT_COLORS: Record<string, string> = {
  High: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  Medium:
    "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border-yellow-500/30",
  Low: "bg-muted text-muted-foreground border-border",
};

const SIGNAL_COLORS: Record<string, string> = {
  BUY: "bg-green-500/15 text-green-600 dark:text-green-400 border-green-500/30",
  SELL: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  HOLD: "bg-muted text-muted-foreground border-border",
  AVOID:
    "bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30",
};

// ── Per-row event card ────────────────────────────────────────────────────────

function TokenCostLog({
  event,
  usdThbRate,
}: {
  event: EconomicEvent;
  usdThbRate: number;
}) {
  const {
    llm_input_tokens,
    llm_output_tokens,
    llm_total_tokens,
    llm_cost_usd,
    llm_duration_ms,
    llm_model,
    llm_provider,
  } = event;
  if (!llm_total_tokens && !llm_cost_usd) return null;

  const costThb = llm_cost_usd != null ? llm_cost_usd * usdThbRate : null;

  return (
    <div className="rounded-md bg-black/5 dark:bg-white/5 border border-border/50 px-3 py-2 font-mono text-xs space-y-0.5">
      <div className="flex items-center gap-2 text-muted-foreground">
        <span className="text-primary/70">▶</span>
        <span className="font-semibold text-foreground">
          {llm_model ?? "unknown"}
        </span>
        <span>·</span>
        <span>{llm_provider ?? "—"}</span>
        {llm_duration_ms != null && (
          <>
            <span>·</span>
            <span>{llm_duration_ms.toLocaleString()}ms</span>
          </>
        )}
      </div>
      {llm_total_tokens != null && (
        <div className="pl-4 text-muted-foreground">
          <span className="text-blue-500 dark:text-blue-400">in</span>{" "}
          {(llm_input_tokens ?? 0).toLocaleString()}
          <span className="mx-1 opacity-40">·</span>
          <span className="text-green-500 dark:text-green-400">out</span>{" "}
          {(llm_output_tokens ?? 0).toLocaleString()}
          <span className="mx-1 opacity-40">·</span>
          <span className="text-foreground font-medium">total</span>{" "}
          {llm_total_tokens.toLocaleString()} tokens
        </div>
      )}
      {llm_cost_usd != null && (
        <div className="pl-4 text-muted-foreground">
          <span className="text-yellow-600 dark:text-yellow-400">cost</span>{" "}
          <span className="text-foreground">${llm_cost_usd.toFixed(8)}</span>
          {costThb != null && (
            <span className="ml-1 opacity-70">· ฿{costThb.toFixed(6)}</span>
          )}
        </div>
      )}
    </div>
  );
}

interface DebugAnalysisResult {
  input_prompt: { role: string; content: string }[];
  raw_response: string;
  parsed_json: Record<string, unknown> | null;
  signal: string | null;
  summary: string | null;
}

export function EventRow({
  event,
  onAnalyzed,
  onActualSaved,
  usdThbRate,
  isNextActive,
}: {
  event: EconomicEvent;
  onAnalyzed: (updated: EconomicEvent) => void;
  onActualSaved: (updated: EconomicEvent) => void;
  usdThbRate: number;
  isNextActive?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [actualDraft, setActualDraft] = useState(event.actual ?? "");
  const [savingActual, setSavingActual] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugData, setDebugData] = useState<DebugAnalysisResult | null>(null);
  const [debugLoading, setDebugLoading] = useState(false);
  const past = isPast(event.event_utc);

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      const updated = await apiRequest<EconomicEvent>(
        `/news/${event.id}/analyze`,
        { method: "POST" },
      );
      onAnalyzed(updated);
      setExpanded(true);
    } catch {
      // error stored server-side, refresh row
    } finally {
      setAnalyzing(false);
    }
  }

  function handleDebugToggle() {
    setDebugOpen((v) => !v);
  }

  async function handleDebugRerun() {
    setDebugLoading(true);
    try {
      const data = await apiRequest<DebugAnalysisResult>(
        `/news/${event.id}/analyze-debug`,
        { method: "POST" },
      );
      setDebugData(data);
    } catch (e) {
      setDebugData({
        input_prompt: [],
        raw_response: e instanceof Error ? e.message : "Request failed",
        parsed_json: null,
        signal: null,
        summary: null,
      });
    } finally {
      setDebugLoading(false);
    }
  }

  async function handleActualKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key !== "Enter") return;
    setSavingActual(true);
    try {
      const updated = await apiRequest<EconomicEvent>(`/news/${event.id}`, {
        method: "PATCH",
        body: JSON.stringify({ actual: actualDraft || null }),
      });
      onActualSaved(updated);
    } finally {
      setSavingActual(false);
    }
  }

  return (
    <div
      className={`border rounded-lg overflow-hidden ${past ? "opacity-60" : ""} ${isNextActive ? "border-blue-500/50 dark:border-blue-500/30 bg-blue-50/50 dark:bg-blue-900/10 shadow-sm ring-1 ring-blue-500/20" : ""}`}
    >
      {/* Main row */}
      <div className="flex items-center gap-3 px-4 py-3 flex-wrap sm:flex-nowrap">
        {/* Time (Bangkok) */}
        <div
          className={`flex items-center gap-1 w-17 shrink-0 text-sm font-mono ${isNextActive ? "text-blue-600 dark:text-blue-400 font-medium" : "text-muted-foreground"}`}
        >
          {isNextActive ? (
            <span
              className="text-blue-500 text-[10px] w-2.5 flex justify-center pt-px"
              title="Next Event"
            >
              ▶
            </span>
          ) : (
            <span className="w-2.5" />
          )}
          <span>{toBangkokTime(event.event_utc)}</span>
        </div>

        {/* Currency */}
        <span className="font-semibold w-10 shrink-0 text-sm">
          {event.currency}
        </span>

        {/* Impact badge */}
        <Badge
          variant="outline"
          className={`shrink-0 text-xs ${IMPACT_COLORS[event.impact] ?? ""}`}
        >
          {event.impact}
        </Badge>

        {/* Title */}
        <span className="flex-1 text-sm font-medium min-w-0 truncate">
          {event.title}
        </span>

        {/* Forecast / Previous / Actual */}
        <div className="flex gap-3 text-xs text-muted-foreground shrink-0">
          <span>
            Prev:{" "}
            <span className="text-foreground">{event.previous ?? "—"}</span>
          </span>
          <span>
            Fore:{" "}
            <span className="text-foreground">{event.forecast ?? "—"}</span>
          </span>
          <span>
            Act:&nbsp;
            {past ? (
              <span className="inline-flex items-center gap-1">
                {savingActual ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Input
                    className="h-5 w-20 px-1 text-xs"
                    value={actualDraft}
                    placeholder="enter"
                    onChange={(e) => setActualDraft(e.target.value)}
                    onKeyDown={handleActualKeyDown}
                    title="Type actual value and press Enter to save"
                  />
                )}
              </span>
            ) : (
              <span>—</span>
            )}
          </span>
        </div>

        {/* LLM signal badge */}
        {event.llm_signal ? (
          <Badge
            variant="outline"
            className={`text-xs shrink-0 ${SIGNAL_COLORS[event.llm_signal] ?? ""}`}
          >
            {event.llm_signal}
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="text-xs shrink-0 text-muted-foreground"
          >
            —
          </Badge>
        )}

        {/* Analyze button */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 shrink-0"
          onClick={handleAnalyze}
          disabled={analyzing}
          title="Run LLM analysis"
        >
          {analyzing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Cpu className="h-3.5 w-3.5" />
          )}
        </Button>

        {/* Expand toggle (only if there's something to show) */}
        {(event.llm_summary ||
          event.affected_symbols.length > 0 ||
          event.analysis_error) && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1 shrink-0"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </Button>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t bg-muted/40 px-4 py-3 space-y-2 text-sm">
          {/* Affected symbols */}
          {event.affected_symbols.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {event.affected_symbols.map((s) => (
                <Badge key={s} variant="secondary" className="text-xs">
                  {s}
                </Badge>
              ))}
            </div>
          )}

          {/* LLM summary */}
          {event.llm_summary && (
            <p className="text-muted-foreground leading-relaxed">
              {event.llm_summary}
            </p>
          )}

          {/* Token / cost pipeline log */}
          <TokenCostLog event={event} usdThbRate={usdThbRate} />

          {/* LLM Debug — collapsible raw prompt + response */}
          {(event.llm_raw_response || event.llm_signal) && (
            <div className="rounded-md border border-border/50 overflow-hidden">
              <button
                className="w-full flex items-center gap-2 px-3 py-2 text-xs font-mono text-muted-foreground hover:bg-muted/50 transition-colors"
                onClick={handleDebugToggle}
              >
                <Terminal className="h-3.5 w-3.5 shrink-0" />
                <span className="font-semibold">LLM Debug</span>
                {debugLoading && (
                  <Loader2 className="h-3 w-3 animate-spin ml-1" />
                )}
                <span className="ml-auto">
                  {debugOpen ? (
                    <ChevronUp className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" />
                  )}
                </span>
              </button>
              {debugOpen && (
                <div className="border-t border-border/50 bg-black/5 dark:bg-white/5 px-3 py-2 space-y-3 font-mono text-xs">
                  {/* Stored raw response (always available after analysis) */}
                  {(event.llm_raw_response || debugData?.raw_response) && (
                    <div>
                      <div className="text-green-500 dark:text-green-400 mb-1">
                        ◀ <span className="font-semibold">raw response</span>
                        <span className="ml-2 opacity-50 text-muted-foreground">
                          (stored)
                        </span>
                      </div>
                      <pre className="whitespace-pre-wrap wrap-break-word text-muted-foreground leading-relaxed pl-4 border-l-2 border-green-500/40">
                        {event.llm_raw_response ?? debugData?.raw_response}
                      </pre>
                    </div>
                  )}
                  {/* Full prompt + fresh response from debug endpoint */}
                  {debugData && (
                    <>
                      <div className="border-t border-border/30 pt-3">
                        <div className="text-yellow-500 dark:text-yellow-400 mb-2 font-semibold">
                          ↺ fresh re-run
                        </div>
                        {debugData.input_prompt.map((msg, i) => (
                          <div key={i} className="mb-2">
                            <div className="text-primary/70 mb-1">
                              ▶{" "}
                              <span className="font-semibold">{msg.role}</span>
                            </div>
                            <pre className="whitespace-pre-wrap wrap-break-word text-muted-foreground leading-relaxed pl-4 border-l-2 border-border/40">
                              {msg.content}
                            </pre>
                          </div>
                        ))}
                        <div>
                          <div className="text-green-500 dark:text-green-400 mb-1">
                            ◀{" "}
                            <span className="font-semibold">raw response</span>
                          </div>
                          <pre className="whitespace-pre-wrap wrap-break-word text-muted-foreground leading-relaxed pl-4 border-l-2 border-green-500/40">
                            {debugData.raw_response}
                          </pre>
                        </div>
                      </div>
                    </>
                  )}
                  {/* Re-run button */}
                  <button
                    className="text-xs text-primary/70 hover:text-primary underline disabled:opacity-50"
                    onClick={handleDebugRerun}
                    disabled={debugLoading}
                  >
                    {debugData
                      ? "↺ re-run fresh"
                      : "Run to see full prompt + fresh response"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Analyzed at */}
          {event.llm_analyzed_at && (
            <p className="text-xs text-muted-foreground">
              Analyzed{" "}
              {toBangkok(event.llm_analyzed_at, {
                dateStyle: "short",
                timeStyle: "short",
              })}
            </p>
          )}

          {/* Error */}
          {event.analysis_error && (
            <div className="flex items-start gap-2 text-destructive text-xs">
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{event.analysis_error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
