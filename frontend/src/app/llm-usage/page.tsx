"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { AppHeader } from "@/components/app-header";
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

  useEffect(() => {
    llmUsageApi
      .getPricing()
      .then(setPricing)
      .catch(() => { /* pricing is supplemental */ });
  }, []);

  useEffect(() => {
    void loadPeriodData(period, granularity);
  }, [period, granularity, loadPeriodData]);

  const periodSelector = (
    <div className="flex items-center gap-1 rounded-lg border p-1">
      {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
        <Button
          key={p}
          variant={period === p ? "default" : "ghost"}
          size="sm"
          className="h-7 px-2.5 text-xs"
          onClick={() => setPeriod(p)}
        >
          {PERIOD_LABELS[p]}
        </Button>
      ))}
    </div>
  );

  return (
    <SidebarInset>
      <AppHeader
        title="LLM Usage"
        subtitle="Token consumption and cost across all AI providers"
        actions={periodSelector}
        showAccountSelector={false}
        showConnectionStatus={false}
      />

      <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
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
              <div key={i} className="h-28 rounded-lg border bg-muted/40 animate-pulse" />
            ))}
          </div>
        )}

        {/* ── Charts Row ── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            {!loading && timeseries.length >= 0 ? (
              <LLMUsageTimeseriesChart
                data={timeseries}
                granularity={granularity}
                onGranularityChange={setGranularity}
              />
            ) : (
              <div className="h-72 rounded-lg border bg-muted/40 animate-pulse" />
            )}
          </div>
          <div className="lg:col-span-1">
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
    </SidebarInset>
  );
}
