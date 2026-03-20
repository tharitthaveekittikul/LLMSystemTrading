"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  RefreshCw,
  Download,
  Cpu,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  Loader2,
  List,
  Calendar,
  Terminal,
} from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api";
import type { EconomicEvent } from "@/types/trading";
import { toast } from "sonner";

const REFRESH_INTERVAL_MS = 60_000;

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

/** Convert UTC ISO string to Bangkok (UTC+7) display string */
function toBangkok(utcStr: string, opts?: Intl.DateTimeFormatOptions): string {
  return new Date(utcStr).toLocaleString("en-GB", {
    timeZone: "Asia/Bangkok",
    hour12: false,
    ...opts,
  });
}

function toBangkokDate(utcStr: string): string {
  return toBangkok(utcStr, {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

function toBangkokTime(utcStr: string): string {
  return toBangkok(utcStr, { hour: "2-digit", minute: "2-digit" });
}

/** Group events by their Bangkok calendar date */
function groupByDate(events: EconomicEvent[]): Map<string, EconomicEvent[]> {
  const map = new Map<string, EconomicEvent[]>();
  for (const ev of events) {
    const key = toBangkokDate(ev.event_utc);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(ev);
  }
  return map;
}

function isPast(utcStr: string): boolean {
  return new Date(utcStr) < new Date();
}

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

function EventRow({
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

// ── Page ──────────────────────────────────────────────────────────────────────

const IMPACT_FILTERS = ["All", "High", "Medium", "Low"] as const;
type ImpactFilter = (typeof IMPACT_FILTERS)[number];

export default function NewsPage() {
  const [events, setEvents] = useState<EconomicEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const nextEventTime = useMemo(() => {
    const futureEvents = events.filter((ev) => !isPast(ev.event_utc));
    if (futureEvents.length === 0) return null;
    const closest = futureEvents.reduce((a, b) => {
      return new Date(b.event_utc) < new Date(a.event_utc) ? b : a;
    });
    return closest.event_utc;
  }, [events]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>("All");
  const [currencyFilter, setCurrencyFilter] = useState<string>("");
  const [fetchingNews, setFetchingNews] = useState(false);
  const [analyzingToday, setAnalyzingToday] = useState(false);
  const [viewMode, setViewMode] = useState<"list" | "day">("day");
  const [selectedDateIdx, setSelectedDateIdx] = useState(0);
  const [usdThbRate, setUsdThbRate] = useState(35.0);

  const fetchEvents = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      else setRefreshing(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (impactFilter !== "All") params.set("impact", impactFilter);
        if (currencyFilter.trim())
          params.set("currency", currencyFilter.trim());
        const qs = params.toString();
        const data = await apiRequest<EconomicEvent[]>(
          `/news${qs ? `?${qs}` : ""}`,
        );
        setEvents(data);
        setLastRefreshed(new Date());
        if (!silent) {
          const todayKey = toBangkokDate(new Date().toISOString());
          const keys = Array.from(groupByDate(data).keys());
          const todayIdx = keys.indexOf(todayKey);
          setSelectedDateIdx(todayIdx >= 0 ? todayIdx : 0);
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load news events",
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [impactFilter, currencyFilter],
  );

  useEffect(() => {
    fetchEvents(false);
  }, [fetchEvents]);
  useEffect(() => {
    const id = setInterval(() => fetchEvents(true), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchEvents]);

  useEffect(() => {
    apiRequest<{ usd_thb_rate: number }>("/llm-usage/summary?period=day")
      .then((d) => setUsdThbRate(d.usd_thb_rate))
      .catch(() => {});
  }, []);

  function handleEventUpdate(updated: EconomicEvent) {
    setEvents((prev) =>
      prev.map((ev) => (ev.id === updated.id ? updated : ev)),
    );
  }

  async function handleFetchNow() {
    setFetchingNews(true);
    try {
      await apiRequest<{ stored: number }>("/news/fetch", { method: "POST" });
      await fetchEvents(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setFetchingNews(false);
    }
  }

  async function handleAnalyzeToday() {
    setAnalyzingToday(true);
    try {
      const res = await apiRequest<{ analyzed: number }>(
        "/news/analyze-today",
        {
          method: "POST",
        },
      );
      if (res.analyzed === 0) {
        toast.info("No unanalyzed HIGH-impact events found for today.");
      } else {
        toast.success(`Analyzed ${res.analyzed} event(s) successfully.`);
      }
      await fetchEvents(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
      toast.error("Analysis failed.");
    } finally {
      setAnalyzingToday(false);
    }
  }

  const grouped = groupByDate(events);
  const dateKeys = Array.from(grouped.keys());
  const clampedIdx = Math.min(
    selectedDateIdx,
    Math.max(0, dateKeys.length - 1),
  );

  const actions = (
    <div className="flex items-center gap-2 flex-wrap">
      {lastRefreshed && (
        <span className="text-xs text-muted-foreground hidden sm:inline">
          {lastRefreshed.toLocaleTimeString()}
        </span>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={() => fetchEvents(true)}
        disabled={refreshing}
      >
        <RefreshCw
          className={`h-4 w-4 mr-1 ${refreshing ? "animate-spin" : ""}`}
        />
        Refresh
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={handleFetchNow}
        disabled={fetchingNews}
      >
        {fetchingNews ? (
          <Loader2 className="h-4 w-4 mr-1 animate-spin" />
        ) : (
          <Download className="h-4 w-4 mr-1" />
        )}
        Fetch Now
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={handleAnalyzeToday}
        disabled={analyzingToday}
      >
        {analyzingToday ? (
          <Loader2 className="h-4 w-4 mr-1 animate-spin" />
        ) : (
          <Cpu className="h-4 w-4 mr-1" />
        )}
        Analyze Today
      </Button>
    </div>
  );

  return (
    <SidebarInset>
      <AppHeader
        title="Economic Calendar"
        subtitle="ForexFactory news with LLM analysis (Bangkok time)"
        actions={actions}
        showAccountSelector={false}
      />

      {/* Sticky controls */}
      <div className="sticky top-0 z-10 bg-background border-b px-4 sm:px-6 py-3 space-y-2">
        {/* Filters + view toggle */}
        <div className="flex items-center gap-2 flex-wrap">
          {IMPACT_FILTERS.map((f) => (
            <Button
              key={f}
              variant={impactFilter === f ? "default" : "outline"}
              size="sm"
              onClick={() => setImpactFilter(f)}
            >
              {f}
            </Button>
          ))}
          <Input
            className="h-8 w-32 text-sm"
            placeholder="Currency…"
            value={currencyFilter}
            onChange={(e) => setCurrencyFilter(e.target.value.toUpperCase())}
          />
          <div className="ml-auto flex items-center gap-1 border rounded-md p-0.5">
            <Button
              variant={viewMode === "list" ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2"
              onClick={() => setViewMode("list")}
              title="List view"
            >
              <List className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={viewMode === "day" ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2"
              onClick={() => setViewMode("day")}
              title="Day view"
            >
              <Calendar className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Day navigation (day view only) */}
        {viewMode === "day" && dateKeys.length > 0 && (
          <div className="flex items-center justify-between">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelectedDateIdx((i) => Math.max(0, i - 1))}
              disabled={clampedIdx === 0}
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Prev
            </Button>
            <span className="text-sm font-semibold">
              {dateKeys[clampedIdx]}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setSelectedDateIdx((i) => Math.min(dateKeys.length - 1, i + 1))
              }
              disabled={clampedIdx === dateKeys.length - 1}
            >
              Next
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        )}
      </div>

      <div className="p-4 sm:p-6 space-y-4">
        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 text-destructive text-sm border border-destructive/30 rounded-md px-4 py-3 bg-destructive/5">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 rounded-lg bg-muted animate-pulse" />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && events.length === 0 && !error && (
          <div className="text-center py-16 text-muted-foreground">
            <p className="text-sm">No events found for this week.</p>
            <p className="text-xs mt-1">
              Click &quot;Fetch Now&quot; to load the latest calendar.
            </p>
          </div>
        )}

        {/* Events — list view */}
        {!loading &&
          viewMode === "list" &&
          Array.from(grouped.entries()).map(([dateLabel, dayEvents]) => (
            <div key={dateLabel} className="space-y-2">
              <h3 className="text-sm font-semibold text-muted-foreground py-1">
                {dateLabel}
              </h3>
              {dayEvents.map((ev) => (
                <EventRow
                  key={ev.id}
                  event={ev}
                  onAnalyzed={handleEventUpdate}
                  onActualSaved={handleEventUpdate}
                  usdThbRate={usdThbRate}
                  isNextActive={ev.event_utc === nextEventTime}
                />
              ))}
            </div>
          ))}

        {/* Events — day view */}
        {!loading && viewMode === "day" && dateKeys.length > 0 && (
          <div className="space-y-2">
            {(grouped.get(dateKeys[clampedIdx]) ?? []).map((ev) => (
              <EventRow
                key={ev.id}
                event={ev}
                onAnalyzed={handleEventUpdate}
                onActualSaved={handleEventUpdate}
                usdThbRate={usdThbRate}
                isNextActive={ev.event_utc === nextEventTime}
              />
            ))}
          </div>
        )}
      </div>
    </SidebarInset>
  );
}
