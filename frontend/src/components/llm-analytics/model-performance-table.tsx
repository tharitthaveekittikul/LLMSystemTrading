"use client"
import { useState } from "react"
import { ArrowUpDown } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ModelPerformanceRow } from "@/types/trading"

interface Props {
  data: ModelPerformanceRow[]
}

type SortKey = keyof ModelPerformanceRow
type SortDir = "asc" | "desc"

function badge(provider: string) {
  const colors: Record<string, string> = {
    google: "bg-blue-100 text-blue-800",
    anthropic: "bg-orange-100 text-orange-800",
    openai: "bg-green-100 text-green-800",
    openrouter: "bg-purple-100 text-purple-800",
  }
  return colors[provider] ?? "bg-muted text-muted-foreground"
}

export function ModelPerformanceTable({ data }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("total_pnl_usd")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc")
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey] as number
    const bv = b[sortKey] as number
    return sortDir === "asc" ? av - bv : bv - av
  })

  const cols: { key: SortKey; label: string; fmt: (r: ModelPerformanceRow) => string }[] = [
    { key: "runs_participated", label: "Runs", fmt: r => r.runs_participated.toString() },
    { key: "trades_triggered", label: "Trades", fmt: r => r.trades_triggered.toString() },
    { key: "win_rate", label: "Win %", fmt: r => r.trades_triggered > 0 ? `${(r.win_rate * 100).toFixed(1)}%` : "—" },
    { key: "avg_profit_usd", label: "Avg Profit", fmt: r => r.trades_triggered > 0 ? `$${r.avg_profit_usd.toFixed(2)}` : "—" },
    { key: "total_pnl_usd", label: "Total P&L", fmt: r => `$${r.total_pnl_usd.toFixed(2)}` },
    { key: "avg_cost_usd", label: "Cost/Call", fmt: r => `$${r.avg_cost_usd.toFixed(5)}` },
    { key: "profit_per_dollar", label: "Profit/$", fmt: r => r.profit_per_dollar.toFixed(2) },
    { key: "avg_latency_ms", label: "Latency", fmt: r => `${r.avg_latency_ms.toFixed(0)} ms` },
  ]

  if (!data.length) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Model Performance</CardTitle></CardHeader>
        <CardContent>
          <div className="h-24 flex items-center justify-center text-muted-foreground text-sm">No data</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Model Performance</CardTitle></CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Model</th>
                {cols.map(c => (
                  <th
                    key={c.key}
                    className="text-right px-3 py-2 font-medium text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                    onClick={() => handleSort(c.key)}
                  >
                    <span className="inline-flex items-center gap-1">
                      {c.label}
                      <ArrowUpDown className="h-3 w-3" />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(row => (
                <tr key={row.model} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-4 py-2">
                    <div className="font-medium truncate max-w-[200px]" title={row.model}>{row.model}</div>
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${badge(row.provider)}`}>
                      {row.provider}
                    </span>
                  </td>
                  {cols.map(c => {
                    const raw = c.key === "total_pnl_usd" ? row.total_pnl_usd : null
                    return (
                      <td
                        key={c.key}
                        className={`px-3 py-2 text-right tabular-nums ${raw !== null ? (raw > 0 ? "text-green-600" : raw < 0 ? "text-red-600" : "") : ""}`}
                      >
                        {c.fmt(row)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
