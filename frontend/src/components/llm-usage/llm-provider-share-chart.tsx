"use client"

import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMUsageSummary } from "@/types/trading"

// Minimal, harmonious muted palette — one distinct hue per provider
const COLORS: Record<string, string> = {
  google:     "#6366f1", // indigo
  anthropic:  "#f59e0b", // amber
  openai:     "#10b981", // emerald
  openrouter: "#ec4899", // pink
}

const DEFAULT_COLOR = "#94a3b8" // slate-400 for unknown providers

interface ProviderShareProps {
  summary: LLMUsageSummary
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-semibold capitalize">{name}</p>
      <p className="text-muted-foreground">${(value as number).toFixed(6)} USD</p>
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomLegend({ payload }: any) {
  if (!payload?.length) return null
  return (
    <div className="flex flex-col gap-1 mt-2">
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {payload.map((entry: any) => (
        <div key={entry.value} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="capitalize text-muted-foreground">{entry.value}</span>
        </div>
      ))}
    </div>
  )
}

export function LLMProviderShareChart({ summary }: ProviderShareProps) {
  const data = Object.entries(summary.by_provider)
    .map(([name, stats]) => ({ name, value: stats.cost_usd }))
    .filter(d => d.value > 0)

  if (data.length === 0) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="text-sm font-medium">Provider Share</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center h-32">
          <p className="text-sm text-muted-foreground">No data yet</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-sm font-medium">Provider Share</CardTitle>
        <p className="text-xs text-muted-foreground">by cost (USD)</p>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={80}
              innerRadius={50}
              strokeWidth={2}
            >
              {data.map(entry => (
                <Cell
                  key={entry.name}
                  fill={COLORS[entry.name] ?? DEFAULT_COLOR}
                />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend content={<CustomLegend />} />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
