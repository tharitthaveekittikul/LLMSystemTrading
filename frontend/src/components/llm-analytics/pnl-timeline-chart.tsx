"use client"
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMTimelinePoint } from "@/types/trading"

interface Props {
  pnlData: LLMTimelinePoint[]
  costData: LLMTimelinePoint[]
}

const COLORS = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4"]

function buildChartRows(points: LLMTimelinePoint[]): { date: string; [model: string]: number | string }[] {
  return points.map(p => ({ date: p.date, ...p.by_model }))
}

function allModels(points: LLMTimelinePoint[]): string[] {
  const s = new Set<string>()
  points.forEach(p => Object.keys(p.by_model).forEach(m => s.add(m)))
  return Array.from(s).sort()
}

export function PnlTimelineChart({ pnlData, costData }: Props) {
  const pnlModels = allModels(pnlData)
  const costModels = allModels(costData)

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Daily P&L by Model</CardTitle></CardHeader>
        <CardContent>
          {!pnlData.length ? (
            <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={buildChartRows(pnlData)} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `$${v.toFixed(0)}`} />
                <Tooltip
                  formatter={(v: number, name: string) => [`$${v.toFixed(2)}`, name]}
                  labelFormatter={l => `Date: ${l}`}
                  contentStyle={{ fontSize: 11 }}
                />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {pnlModels.map((m, i) => (
                  <Line
                    key={m}
                    type="monotone"
                    dataKey={m}
                    stroke={COLORS[i % COLORS.length]}
                    dot={false}
                    strokeWidth={1.5}
                    name={m.length > 20 ? m.slice(0, 18) + "…" : m}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Daily Cost by Model</CardTitle></CardHeader>
        <CardContent>
          {!costData.length ? (
            <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={buildChartRows(costData)} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `$${v.toFixed(3)}`} />
                <Tooltip
                  formatter={(v: number, name: string) => [`$${v.toFixed(5)}`, name]}
                  labelFormatter={l => `Date: ${l}`}
                  contentStyle={{ fontSize: 11 }}
                />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {costModels.map((m, i) => (
                  <Bar
                    key={m}
                    dataKey={m}
                    stackId="cost"
                    fill={COLORS[i % COLORS.length]}
                    name={m.length > 20 ? m.slice(0, 18) + "…" : m}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
