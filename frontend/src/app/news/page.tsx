"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  RefreshCw,
  Download,
  Cpu,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  Loader2,
  List,
  Calendar,
} from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api";
import type { EconomicEvent } from "@/types/trading";
import { toast } from "sonner";
import { EventRow } from "@/components/news/event-row";
import { toBangkokDate, groupByDate, isPast } from "@/lib/news-time";

const REFRESH_INTERVAL_MS = 60_000;

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
  const [symbolFilter, setSymbolFilter] = useState<string>("");
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
        if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim());
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
    [impactFilter, currencyFilter, symbolFilter],
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
          <Input
            className="h-8 w-32 text-sm"
            placeholder="Symbol…"
            title="Filter to events affecting this trading symbol (e.g. EURUSD)"
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
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
