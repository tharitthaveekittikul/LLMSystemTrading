"use client"
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ModelPerformanceRow } from "@/types/trading"

interface Props {
  data: ModelPerformanceRow[]
}

const ACTION_COLORS: Record<string, string> = {
  buy: "#10b981",
  sell: "#ef4444",
  hold: "#6366f1",
  skip: "#9ca3af",
}

export function ActionDistributionChart({ data }: Props) {
  if (!data.length) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Action Distribution by Model</CardTitle></CardHeader>
        <CardContent>
          <div className="h-24 flex items-center justify-center text-muted-foreground text-sm">No data</div>
        </CardContent>
      </Card>
    )
  }

  const actions = Array.from(
    new Set(data.flatMap(r => Object.keys(r.action_dist)))
  ).sort()

  const chartData = data.map(r => ({
    model: r.model.length > 20 ? r.model.slice(0, 18) + "…" : r.model,
    fullModel: r.model,
    ...Object.fromEntries(
      actions.map(a => [a, Math.round((r.action_dist[a] ?? 0) * 100)])
    ),
  }))

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Action Distribution by Model</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 20, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} className="stroke-border" />
            <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="model" tick={{ fontSize: 11 }} width={120} />
            <Tooltip
              formatter={(v: number, name: string) => [`${v}%`, name.toUpperCase()]}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const full = chartData.find(d => d.model === label)?.fullModel ?? label
                return (
                  <div className="bg-background border rounded p-2 text-xs shadow space-y-0.5">
                    <p className="font-medium mb-1">{full}</p>
                    {payload.map(p => (
                      <p key={p.name} style={{ color: p.fill }}>
                        {String(p.name).toUpperCase()}: {p.value}%
                      </p>
                    ))}
                  </div>
                )
              }}
            />
            <Legend formatter={v => v.toUpperCase()} wrapperStyle={{ fontSize: 11 }} />
            {actions.map(a => (
              <Bar key={a} dataKey={a} stackId="a" fill={ACTION_COLORS[a] ?? "#9ca3af"} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
