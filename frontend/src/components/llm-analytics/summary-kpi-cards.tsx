"use client"
import { Card, CardContent } from "@/components/ui/card"
import type { LLMAnalyticsSummary } from "@/types/trading"

interface Props {
  data: LLMAnalyticsSummary | null
}

export function SummaryKpiCards({ data }: Props) {
  const fmt = (v: number, decimals = 2, prefix = "", suffix = "") =>
    `${prefix}${v.toFixed(decimals)}${suffix}`

  const kpis = [
    {
      label: "Best Win Rate",
      value: data ? fmt(data.best_win_rate * 100, 1, "", "%") : "—",
      sub: data?.best_win_rate_model ?? "—",
    },
    {
      label: "Best ROI (P&L / Cost)",
      value: data ? fmt(data.best_roi, 2, "", "x") : "—",
      sub: data?.best_roi_model ?? "—",
    },
    {
      label: "Fastest Model",
      value: data ? fmt(data.fastest_ms, 0, "", " ms") : "—",
      sub: data?.fastest_model ?? "—",
    },
    {
      label: "Total Spend",
      value: data ? `$${data.total_cost_usd.toFixed(4)}` : "—",
      sub: data ? `${data.total_trades_triggered} trades triggered` : "—",
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {kpis.map(({ label, value, sub }) => (
        <Card key={label}>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-xl font-semibold tabular-nums">{value}</p>
            <p className="text-xs text-muted-foreground truncate mt-0.5">{sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
