"use client"
import { useEffect, useState } from "react"
import { llmAnalyticsApi } from "@/lib/api"
import type {
  LLMAnalyticsSummary,
  ModelPerformanceRow,
  LLMHeatmapResponse,
  LLMTimelinePoint,
  PipelineCombinationRow,
  SymbolPnLRow,
} from "@/types/trading"
import { SidebarInset } from "@/components/ui/sidebar"
import { AppHeader } from "@/components/app-header"
import { SummaryKpiCards } from "@/components/llm-analytics/summary-kpi-cards"
import { ModelPerformanceTable } from "@/components/llm-analytics/model-performance-table"
import { ModelSymbolHeatmap } from "@/components/llm-analytics/model-symbol-heatmap"
import { CostVsWinrateScatter } from "@/components/llm-analytics/cost-vs-winrate-scatter"
import { ActionDistributionChart } from "@/components/llm-analytics/action-distribution-chart"
import { PnlTimelineChart } from "@/components/llm-analytics/pnl-timeline-chart"
import { PipelineCombinationsTable } from "@/components/llm-analytics/pipeline-combinations-table"
import { SymbolPnLTable } from "@/components/llm-analytics/symbol-pnl-table"
import { LearningTab } from "@/components/llm-analytics/learning-tab"
import { Button } from "@/components/ui/button"
import { RefreshCw } from "lucide-react"

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
]

const TABS = ["Models", "Pipelines", "P&L Attribution", "Learning"] as const
type Tab = typeof TABS[number]

export default function LLMAnalyticsPage() {
  const [days, setDays] = useState(30)
  const [tab, setTab] = useState<Tab>("Models")
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<LLMAnalyticsSummary | null>(null)
  const [performance, setPerformance] = useState<ModelPerformanceRow[]>([])
  const [heatmap, setHeatmap] = useState<LLMHeatmapResponse | null>(null)
  const [pnlTimeline, setPnlTimeline] = useState<LLMTimelinePoint[]>([])
  const [costTrend, setCostTrend] = useState<LLMTimelinePoint[]>([])
  const [pipelines, setPipelines] = useState<PipelineCombinationRow[]>([])
  const [symbolPnl, setSymbolPnl] = useState<SymbolPnLRow[]>([])
  const [pnlGroupBy, setPnlGroupBy] = useState<"symbol" | "source">("symbol")

  const fetchAll = async (d: number, groupBy: "symbol" | "source" = pnlGroupBy) => {
    setLoading(true)
    try {
      const [s, p, h, pnl, cost, pipe, symPnl] = await Promise.all([
        llmAnalyticsApi.getSummary(d),
        llmAnalyticsApi.getModelPerformance(d),
        llmAnalyticsApi.getHeatmap(d),
        llmAnalyticsApi.getPnlTimeline(d),
        llmAnalyticsApi.getCostTrend(d),
        llmAnalyticsApi.getPipelineCombinations(d),
        llmAnalyticsApi.getSymbolPnl(d, groupBy),
      ])
      setSummary(s)
      setPerformance(p)
      setHeatmap(h)
      setPnlTimeline(pnl)
      setCostTrend(cost)
      setPipelines(pipe)
      setSymbolPnl(symPnl)
    } catch (e) {
      console.error("LLM analytics fetch failed", e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll(days) }, [days])

  const handleGroupByChange = (g: "symbol" | "source") => {
    setPnlGroupBy(g)
    fetchAll(days, g)
  }

  const headerActions = (
    <div className="flex items-center gap-2">
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
  )

  return (
    <SidebarInset>
      <AppHeader
        title="LLM Analytics"
        subtitle="Performance, cost, and profitability per model"
        actions={headerActions}
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
        <SummaryKpiCards data={summary} />

        {/* Tab switcher */}
        <div className="flex rounded-md border overflow-hidden w-fit">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-sm transition-colors ${
                tab === t
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-muted"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "Models" && (
          <>
            <ModelPerformanceTable data={performance} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <ModelSymbolHeatmap data={heatmap} />
              <CostVsWinrateScatter data={performance} />
            </div>
            <ActionDistributionChart data={performance} />
            <PnlTimelineChart pnlData={pnlTimeline} costData={costTrend} />
          </>
        )}

        {tab === "Pipelines" && (
          <PipelineCombinationsTable data={pipelines} />
        )}

        {tab === "P&L Attribution" && (
          <SymbolPnLTable
            data={symbolPnl}
            groupBy={pnlGroupBy}
            onGroupByChange={handleGroupByChange}
          />
        )}

        {tab === "Learning" && (
          <LearningTab days={days} />
        )}
      </div>
    </SidebarInset>
  )
}
