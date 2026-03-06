"use client"

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMUsageSummary } from "@/types/trading"

const COLORS: Record<string, string> = {
  google:    "#3b82f6",
  anthropic: "#f97316",
  openai:    "#22c55e",
}

interface ProviderShareProps {
  summary: LLMUsageSummary
}

export function LLMProviderShareChart({ summary }: ProviderShareProps) {
  const data = Object.entries(summary.by_provider)
    .map(([name, stats]) => ({ name, value: stats.cost_usd }))
    .filter(d => d.value > 0)

  if (data.length === 0) {
    return (
      <Card>
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
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Provider Share (by cost)</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={70}
              innerRadius={40}
            >
              {data.map(entry => (
                <Cell
                  key={entry.name}
                  fill={COLORS[entry.name] ?? "#888"}
                />
              ))}
            </Pie>
            <Tooltip
              formatter={(v: number) => [`$${v.toFixed(6)}`, "Cost"]}
            />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
