"use client"
import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { ArrowLeft } from "lucide-react"
import { AnalyticsKPIBar } from "@/components/analytics/analytics-kpi-bar"
import { AnalyticsHeatmap } from "@/components/analytics/analytics-heatmap"
import { AnalyticsCombinations } from "@/components/analytics/analytics-combinations"
import { PatternGridPanel } from "@/components/analytics/panels/pattern-grid-panel"
import { backtestApi } from "@/lib/api"

interface PatternGroup {
  name: string; trades: number; win_rate: number; total_pnl: number
  avg_win: number; avg_loss: number; profit_factor: number; best_symbol: string
}

type PanelType = React.ComponentType<{ groups: PatternGroup[] }>

const PANEL_MAP: Record<string, PanelType> = {
  pattern_grid: PatternGridPanel,
}

interface AnalyticsSummary {
  run_id: number
  panel_type: string
  total_trades: number | null
  win_rate: number | null
  profit_factor: number | null
  max_drawdown_pct: number | null
  sharpe_ratio: number | null
  total_return_pct: number | null
}

interface HeatmapData {
  labels_x: string[]
  labels_y: string[]
  values: number[][]
}

interface CombinationsData {
  top: Array<{ symbol: string; pattern: string; trades: number; win_rate: number; total_pnl: number; profit_factor: number }>
  worst: Array<{ symbol: string; pattern: string; trades: number; win_rate: number; total_pnl: number; profit_factor: number }>
  recommendations: string[]
}

export default function AnalyticsPage() {
  const { id } = useParams<{ id: string }>()
  const runId = parseInt(id, 10)

  const [summary, setSummary] = useState<AnalyticsSummary | null>(null)
  const [groups, setGroups] = useState<PatternGroup[]>([])
  const [heatmap, setHeatmap] = useState<HeatmapData | null>(null)
  const [combinations, setCombinations] = useState<CombinationsData | null>(null)
  const [metric, setMetric] = useState("win_rate")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [s, g, h, c] = await Promise.all([
          backtestApi.getAnalyticsSummary(runId),
          backtestApi.getAnalyticsGroups(runId, "pattern_name"),
          backtestApi.getAnalyticsHeatmap(runId, "symbol", "pattern_name", metric),
          backtestApi.getAnalyticsCombinations(runId),
        ])
        setSummary(s)
        setGroups(g)
        setHeatmap(h)
        setCombinations(c)
      } catch {
        setError("Failed to load analytics")
      } finally {
        setLoading(false)
      }
    }
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const handleMetricChange = async (m: string) => {
    setMetric(m)
    try {
      const h = await backtestApi.getAnalyticsHeatmap(runId, "symbol", "pattern_name", m)
      setHeatmap(h)
    } catch {
      // silently ignore heatmap refresh errors
    }
  }

  const DetailPanel = summary?.panel_type ? PANEL_MAP[summary.panel_type] : null

  if (loading) return <div className="p-6 text-muted-foreground">Loading analytics...</div>
  if (error) return <div className="p-6 text-red-500">{error}</div>

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/backtest"><ArrowLeft className="h-4 w-4 mr-1" />Back</Link>
        </Button>
        <h1 className="text-xl font-semibold">Backtest Analytics — Run #{runId}</h1>
      </div>

      <AnalyticsKPIBar
        totalTrades={summary?.total_trades ?? null}
        winRate={summary?.win_rate ?? null}
        profitFactor={summary?.profit_factor ?? null}
        maxDrawdown={summary?.max_drawdown_pct ?? null}
        sharpe={summary?.sharpe_ratio ?? null}
        totalReturn={summary?.total_return_pct ?? null}
      />

      <AnalyticsHeatmap data={heatmap} onMetricChange={handleMetricChange} />

      {combinations && (
        <AnalyticsCombinations
          top={combinations.top}
          worst={combinations.worst}
          recommendations={combinations.recommendations}
        />
      )}

      {DetailPanel && (
        <div className="border rounded-lg p-4">
          <DetailPanel groups={groups} />
        </div>
      )}
    </div>
  )
}
