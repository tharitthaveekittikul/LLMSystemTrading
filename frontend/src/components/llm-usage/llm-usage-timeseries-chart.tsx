"use client"

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMTimeseriesPoint } from "@/types/trading"

// Minimal, harmonious muted palette — matches provider-share chart
const PROVIDER_COLORS: Record<string, string> = {
  google:    "#6366f1", // indigo
  anthropic: "#f59e0b", // amber
  openai:    "#10b981", // emerald
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

function formatCostTick(v: number) {
  if (v === 0) return "$0"
  if (v >= 1) return `$${v.toFixed(2)}`
  if (v >= 0.01) return `$${v.toFixed(3)}`
  return `$${v.toFixed(4)}`
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomTooltip({ active, payload, label, granularity }: any) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s: number, p: { value: number }) => s + (p.value ?? 0), 0)
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md space-y-1">
      <p className="font-semibold text-foreground">{formatLabel(label as string, granularity as "daily" | "hourly")}</p>
      {payload.map((p: { name: string; value: number; fill: string }) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: p.fill }} />
          <span className="capitalize text-muted-foreground">{p.name}</span>
          <span className="ml-auto font-mono text-foreground">${p.value?.toFixed(6)}</span>
        </div>
      ))}
      {payload.length > 1 && (
        <div className="border-t pt-1 flex justify-between">
          <span className="text-muted-foreground">Total</span>
          <span className="font-mono font-semibold">${total.toFixed(6)}</span>
        </div>
      )}
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomLegend({ payload }: any) {
  if (!payload?.length) return null
  return (
    <div className="flex flex-wrap gap-3 justify-center mt-1">
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {payload.map((entry: any) => (
        <div key={entry.value} className="flex items-center gap-1.5 text-xs">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="capitalize text-muted-foreground">{entry.value}</span>
        </div>
      ))}
    </div>
  )
}

export function LLMUsageTimeseriesChart({
  data, granularity, onGranularityChange,
}: TimeseriesChartProps) {
  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">Spend Over Time</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">Cost per provider (USD)</p>
          </div>
          <div className="flex rounded-md border text-xs overflow-hidden">
            {(["daily", "hourly"] as const).map(g => (
              <button
                key={g}
                className={`px-2.5 py-1 capitalize transition-colors ${granularity === g ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => onGranularityChange(g)}
              >
                {g === "daily" ? "Daily" : "Hourly"}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={d => formatLabel(d, granularity)}
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={formatCostTick}
              width={56}
            />
            <Tooltip content={<CustomTooltip granularity={granularity} />} />
            <Legend content={<CustomLegend />} />
            {(["google", "anthropic", "openai"] as const).map(p => (
              <Bar key={p} dataKey={p} stackId="a" fill={PROVIDER_COLORS[p]} name={p} radius={p === "openai" ? [3, 3, 0, 0] : [0, 0, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
