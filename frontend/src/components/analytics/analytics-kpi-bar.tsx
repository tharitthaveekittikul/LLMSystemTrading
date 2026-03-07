"use client"
import { Card, CardContent } from "@/components/ui/card"

interface KPIBarProps {
  totalTrades: number | null
  winRate: number | null
  profitFactor: number | null
  maxDrawdown: number | null
  sharpe: number | null
  totalReturn: number | null
}

export function AnalyticsKPIBar({ totalTrades, winRate, profitFactor, maxDrawdown, sharpe, totalReturn }: KPIBarProps) {
  const fmt = (v: number | null, decimals = 2, suffix = "") =>
    v == null ? "—" : `${v.toFixed(decimals)}${suffix}`

  const kpis = [
    { label: "Total Trades", value: totalTrades?.toString() ?? "—" },
    { label: "Win Rate", value: fmt(winRate ? winRate * 100 : null, 1, "%") },
    { label: "Profit Factor", value: fmt(profitFactor) },
    { label: "Max Drawdown", value: fmt(maxDrawdown, 1, "%") },
    { label: "Sharpe Ratio", value: fmt(sharpe) },
    { label: "Total Return", value: fmt(totalReturn, 1, "%") },
  ]

  return (
    <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
      {kpis.map(({ label, value }) => (
        <Card key={label}>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-xl font-semibold tabular-nums">{value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
