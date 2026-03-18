"use client"
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Label,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ModelPerformanceRow } from "@/types/trading"

interface Props {
  data: ModelPerformanceRow[]
}

const COLORS = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4"]

interface DotProps {
  cx?: number
  cy?: number
  payload?: { model: string; color: string; r: number }
}

function CustomDot({ cx, cy, payload }: DotProps) {
  if (!payload || cx == null || cy == null) return null
  return (
    <circle
      cx={cx}
      cy={cy}
      r={payload.r}
      fill={payload.color}
      fillOpacity={0.7}
      stroke={payload.color}
      strokeWidth={1}
    />
  )
}

export function CostVsWinrateScatter({ data }: Props) {
  const withTrades = data.filter(r => r.trades_triggered > 0)

  if (!withTrades.length) {
    return (
      <Card className="h-full">
        <CardHeader><CardTitle className="text-base">Cost vs Win Rate</CardTitle></CardHeader>
        <CardContent>
          <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">No data</div>
        </CardContent>
      </Card>
    )
  }

  const maxTrades = Math.max(...withTrades.map(r => r.trades_triggered), 1)
  const points = withTrades.map((r, i) => ({
    model: r.model,
    x: r.avg_cost_usd * 1000, // cost in milli-USD for readability
    y: r.win_rate * 100,
    r: 4 + (r.trades_triggered / maxTrades) * 12,
    color: COLORS[i % COLORS.length],
  }))

  return (
    <Card className="h-full">
      <CardHeader><CardTitle className="text-base">Cost vs Win Rate</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis type="number" dataKey="x" name="Avg Cost" tick={{ fontSize: 11 }}>
              <Label value="Avg Cost (m$)" position="insideBottom" offset={-15} style={{ fontSize: 11 }} />
            </XAxis>
            <YAxis type="number" dataKey="y" name="Win %" tick={{ fontSize: 11 }}>
              <Label value="Win %" angle={-90} position="insideLeft" offset={10} style={{ fontSize: 11 }} />
            </YAxis>
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const d = payload[0].payload
                return (
                  <div className="bg-background border rounded p-2 text-xs shadow">
                    <p className="font-medium">{d.model}</p>
                    <p>Cost: ${(d.x / 1000).toFixed(5)}</p>
                    <p>Win Rate: {d.y.toFixed(1)}%</p>
                  </div>
                )
              }}
            />
            <Scatter data={points} shape={<CustomDot />} />
          </ScatterChart>
        </ResponsiveContainer>
        <div className="flex flex-wrap gap-2 mt-2">
          {points.map(p => (
            <span key={p.model} className="flex items-center gap-1 text-xs">
              <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: p.color }} />
              <span className="truncate max-w-[120px]" title={p.model}>{p.model}</span>
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
