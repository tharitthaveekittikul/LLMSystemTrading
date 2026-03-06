"use client"

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMTimeseriesPoint } from "@/types/trading"

const PROVIDER_COLORS = {
  google:    "#3b82f6",
  anthropic: "#f97316",
  openai:    "#22c55e",
}

interface TimeseriesChartProps {
  data: LLMTimeseriesPoint[]
  granularity: "daily" | "hourly"
  onGranularityChange: (g: "daily" | "hourly") => void
}

function formatLabel(date: string, granularity: "daily" | "hourly") {
  if (granularity === "hourly") return date.slice(11, 16)
  return date.slice(5) // MM-DD
}

export function LLMUsageTimeseriesChart({
  data, granularity, onGranularityChange,
}: TimeseriesChartProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Spend Over Time</CardTitle>
          <div className="flex rounded-md border text-xs overflow-hidden">
            {(["daily", "hourly"] as const).map(g => (
              <button
                key={g}
                className={`px-2 py-1 capitalize transition-colors ${granularity === g ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => onGranularityChange(g)}
              >
                {g}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="date"
              tickFormatter={d => formatLabel(d, granularity)}
              tick={{ fontSize: 10 }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => `$${Number(v).toFixed(4)}`}
              width={64}
            />
            <Tooltip
              formatter={(v: number) => [`$${Number(v).toFixed(4)}`, ""]}
            />
            <Legend />
            {(["google", "anthropic", "openai"] as const).map(p => (
              <Bar key={p} dataKey={p} stackId="a" fill={PROVIDER_COLORS[p]} name={p} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
