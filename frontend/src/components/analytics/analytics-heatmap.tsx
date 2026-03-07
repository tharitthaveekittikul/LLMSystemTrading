"use client"
import { useState } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

interface HeatmapProps {
  data: { labels_x: string[]; labels_y: string[]; values: number[][] } | null
  onMetricChange?: (metric: string) => void
}

function cellColor(value: number, metric: string): string {
  if (metric === "win_rate") {
    if (value >= 0.6) return "bg-green-600 text-white"
    if (value >= 0.5) return "bg-green-400"
    if (value >= 0.4) return "bg-yellow-400"
    return "bg-red-400 text-white"
  }
  if (value > 0) return "bg-green-500 text-white"
  if (value < 0) return "bg-red-500 text-white"
  return "bg-muted"
}

export function AnalyticsHeatmap({ data, onMetricChange }: HeatmapProps) {
  const [metric, setMetric] = useState("win_rate")

  if (!data) return <div className="h-48 flex items-center justify-center text-muted-foreground">No data</div>

  const handleMetric = (m: string) => {
    setMetric(m)
    onMetricChange?.(m)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Performance Heatmap</h3>
        <Select value={metric} onValueChange={handleMetric}>
          <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="win_rate">Win Rate</SelectItem>
            <SelectItem value="total_pnl">Total P&L</SelectItem>
            <SelectItem value="profit_factor">Profit Factor</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="overflow-x-auto">
        <table className="text-xs border-collapse w-full">
          <thead>
            <tr>
              <th className="p-1 text-left text-muted-foreground">Symbol ↓ / Pattern →</th>
              {data.labels_y.map(y => (
                <th key={y} className="p-1 text-center font-normal text-muted-foreground">{y}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.labels_x.map((x, xi) => (
              <tr key={x}>
                <td className="p-1 font-medium">{x}</td>
                {data.labels_y.map((_, yi) => {
                  const val = data.values[xi]?.[yi] ?? 0
                  const display = metric === "win_rate"
                    ? `${(val * 100).toFixed(0)}%`
                    : val.toFixed(1)
                  return (
                    <td key={yi} className={`p-1 text-center rounded ${cellColor(val, metric)}`}>
                      {display}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
