"use client"

import { DollarSign, Zap, Activity, Cpu } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMUsageSummary } from "@/types/trading"

function formatCost(usd: number): string {
  if (usd === 0) return "$0.00"
  if (usd < 0.001) return `$${usd.toFixed(6)}`
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

interface SummaryCardsProps {
  data: LLMUsageSummary
}

export function LLMUsageSummaryCards({ data }: SummaryCardsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Spend</CardTitle>
          <DollarSign className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatCost(data.total_cost_usd)}</p>
          <p className="text-xs text-muted-foreground mt-1">
            USD <span className="opacity-70 ml-1.5">≈ {(data.total_cost_usd * (data.usd_thb_rate || 36.0)).toLocaleString(undefined, { maximumFractionDigits: 2 })} Baht</span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Tokens</CardTitle>
          <Zap className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatTokens(data.total_tokens)}</p>
          <p className="text-xs text-muted-foreground mt-1">across all calls</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Calls</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{data.total_calls}</p>
          <p className="text-xs text-muted-foreground mt-1">LLM invocations</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Active Models</CardTitle>
          <Cpu className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{data.active_models.length}</p>
          <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
            {data.active_models.slice(0, 2).map(m => (
              <p key={m} className="truncate">{m}</p>
            ))}
            {data.active_models.length > 2 && (
              <p>+{data.active_models.length - 2} more</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
