"use client"
import { useEffect, useState } from "react"
import { llmAnalyticsApi } from "@/lib/api"
import type {
  LLMAnalyticsSummary,
  ModelPerformanceRow,
  LLMHeatmapResponse,
  LLMTimelinePoint,
} from "@/types/trading"
import { SummaryKpiCards } from "@/components/llm-analytics/summary-kpi-cards"
import { ModelPerformanceTable } from "@/components/llm-analytics/model-performance-table"
import { ModelSymbolHeatmap } from "@/components/llm-analytics/model-symbol-heatmap"
import { CostVsWinrateScatter } from "@/components/llm-analytics/cost-vs-winrate-scatter"
import { ActionDistributionChart } from "@/components/llm-analytics/action-distribution-chart"
import { PnlTimelineChart } from "@/components/llm-analytics/pnl-timeline-chart"
import { Button } from "@/components/ui/button"
import { RefreshCw } from "lucide-react"

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
]

export default function LLMAnalyticsPage() {
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<LLMAnalyticsSummary | null>(null)
  const [performance, setPerformance] = useState<ModelPerformanceRow[]>([])
  const [heatmap, setHeatmap] = useState<LLMHeatmapResponse | null>(null)
  const [pnlTimeline, setPnlTimeline] = useState<LLMTimelinePoint[]>([])
  const [costTrend, setCostTrend] = useState<LLMTimelinePoint[]>([])

  const fetchAll = async (d: number) => {
    setLoading(true)
    try {
      const [s, p, h, pnl, cost] = await Promise.all([
        llmAnalyticsApi.getSummary(d),
        llmAnalyticsApi.getModelPerformance(d),
        llmAnalyticsApi.getHeatmap(d),
        llmAnalyticsApi.getPnlTimeline(d),
        llmAnalyticsApi.getCostTrend(d),
      ])
      setSummary(s)
      setPerformance(p)
      setHeatmap(h)
      setPnlTimeline(pnl)
      setCostTrend(cost)
    } catch (e) {
      console.error("LLM analytics fetch failed", e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll(days) }, [days])

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">LLM Model Analytics</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Performance, cost, and profitability per model
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Period selector */}
          <div className="flex rounded-md border overflow-hidden">
            {PERIODS.map(p => (
              <button
                key={p.days}
                onClick={() => setDays(p.days)}
                className={`px-3 py-1.5 text-sm transition-colors ${
                  days === p.days
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchAll(days)}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Section 1: KPI Cards */}
      <SummaryKpiCards data={summary} />

      {/* Section 2: Model Performance Table */}
      <ModelPerformanceTable data={performance} />

      {/* Section 3: Heatmap + Scatter */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ModelSymbolHeatmap data={heatmap} />
        <CostVsWinrateScatter data={performance} />
      </div>

      {/* Section 4: Action Distribution */}
      <ActionDistributionChart data={performance} />

      {/* Section 5: P&L Timeline + Cost Trend */}
      <PnlTimelineChart pnlData={pnlTimeline} costData={costTrend} />
    </div>
  )
}
