"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LLMUsageSummaryCards } from "@/components/llm-usage/llm-usage-summary-cards";
import { LLMUsageTimeseriesChart } from "@/components/llm-usage/llm-usage-timeseries-chart";
import { LLMUsageModelTable } from "@/components/llm-usage/llm-usage-model-table";
import { LLMProviderShareChart } from "@/components/llm-usage/llm-provider-share-chart";
import { LLMPricingReference } from "@/components/llm-usage/llm-pricing-reference";
import { llmUsageApi } from "@/lib/api";
import type {
  LLMUsageSummary,
  LLMTimeseriesPoint,
  LLMModelUsage,
  LLMPricingEntry,
} from "@/types/trading";

type Period = "day" | "week" | "month";
type Granularity = "daily" | "hourly";

const PERIOD_LABELS: Record<Period, string> = {
  day: "Today",
  week: "7 Days",
  month: "30 Days",
};

const PERIOD_DAYS: Record<Period, number> = {
  day: 1,
  week: 7,
  month: 30,
};

export default function LLMUsagePage() {
  const [period, setPeriod] = useState<Period>("month");
  const [granularity, setGranularity] = useState<Granularity>("daily");

  const [summary, setSummary] = useState<LLMUsageSummary | null>(null);
  const [timeseries, setTimeseries] = useState<LLMTimeseriesPoint[]>([]);
  const [modelUsage, setModelUsage] = useState<LLMModelUsage[]>([]);
  const [pricing, setPricing] = useState<LLMPricingEntry[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPeriodData = useCallback(
    async (p: Period, g: Granularity) => {
      setLoading(true);
      setError(null);
      try {
        const [summaryData, timeseriesData, modelData] = await Promise.all([
          llmUsageApi.getSummary(p),
          llmUsageApi.getTimeseries({ granularity: g, days: PERIOD_DAYS[p] }),
          llmUsageApi.getByModel(p),
        ]);
        setSummary(summaryData);
        setTimeseries(timeseriesData);
        setModelUsage(modelData);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load LLM usage data");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // Load pricing once on mount
  useEffect(() => {
    llmUsageApi
      .getPricing()
      .then(setPricing)
      .catch(() => {
        // pricing is supplemental — don't surface as a page-level error
      });
  }, []);

  // Reload when period changes
  useEffect(() => {
    void loadPeriodData(period, granularity);
  }, [period, granularity, loadPeriodData]);

  const handleGranularityChange = (g: Granularity) => {
    setGranularity(g);
  };

  return (
    <div className="p-6 space-y-6">
      {/* ── Page Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">LLM Usage</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Token consumption and cost across all AI providers
          </p>
        </div>

        {/* Period selector */}
        <div className="flex items-center gap-1 rounded-lg border p-1">
          {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
            <Button
              key={p}
              variant={period === p ? "default" : "ghost"}
              size="sm"
              className="h-7 px-3 text-xs"
              onClick={() => setPeriod(p)}
            >
              {PERIOD_LABELS[p]}
            </Button>
          ))}
        </div>
      </div>

      {/* ── Error Alert ── */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* ── Summary Cards ── */}
      {!loading && summary ? (
        <LLMUsageSummaryCards data={summary} />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-24 rounded-lg border bg-muted/40 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* ── Charts Row ── */}
      <div className="grid grid-cols-3 gap-4">
        {/* Timeseries chart — 2/3 width */}
        <div className="col-span-2">
          {!loading && timeseries.length >= 0 ? (
            <LLMUsageTimeseriesChart
              data={timeseries}
              granularity={granularity}
              onGranularityChange={handleGranularityChange}
            />
          ) : (
            <div className="h-72 rounded-lg border bg-muted/40 animate-pulse" />
          )}
        </div>

        {/* Provider share chart — 1/3 width */}
        <div className="col-span-1">
          {!loading && summary ? (
            <LLMProviderShareChart summary={summary} />
          ) : (
            <div className="h-72 rounded-lg border bg-muted/40 animate-pulse" />
          )}
        </div>
      </div>

      {/* ── Model Breakdown Table ── */}
      {!loading && modelUsage.length >= 0 ? (
        <LLMUsageModelTable data={modelUsage} />
      ) : (
        <div className="h-40 rounded-lg border bg-muted/40 animate-pulse" />
      )}

      {/* ── Pricing Reference ── */}
      {pricing.length > 0 && <LLMPricingReference data={pricing} />}
    </div>
  );
}
