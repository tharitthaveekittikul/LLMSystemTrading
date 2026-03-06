"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { LLMModelUsage } from "@/types/trading"

const PROVIDER_BADGE: Record<string, string> = {
  google:    "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  anthropic: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  openai:    "bg-green-500/15 text-green-700 dark:text-green-400",
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

function fmtCost(usd: number) {
  if (usd === 0) return "—"
  if (usd < 0.001) return `$${usd.toFixed(6)}`
  return `$${usd.toFixed(4)}`
}

interface ModelTableProps {
  data: LLMModelUsage[]
}

export function LLMUsageModelTable({ data }: ModelTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Model Breakdown</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="text-left px-4 py-2 font-medium">Model</th>
                <th className="text-right px-4 py-2 font-medium">Calls</th>
                <th className="text-right px-4 py-2 font-medium">Input</th>
                <th className="text-right px-4 py-2 font-medium">Output</th>
                <th className="text-right px-4 py-2 font-medium">Total</th>
                <th className="text-right px-4 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.map(row => (
                <tr key={row.model} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={`text-xs ${PROVIDER_BADGE[row.provider] ?? ""}`}
                      >
                        {row.provider}
                      </Badge>
                      <span className="font-mono text-xs">{row.model}</span>
                    </div>
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums">{row.calls}</td>
                  <td className="text-right px-4 py-2.5 tabular-nums text-muted-foreground">
                    {fmtTokens(row.input_tokens)}
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums text-muted-foreground">
                    {fmtTokens(row.output_tokens)}
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums font-medium">
                    {fmtTokens(row.total_tokens)}
                  </td>
                  <td className="text-right px-4 py-2.5 tabular-nums font-medium">
                    {fmtCost(row.cost_usd)}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    No LLM calls recorded yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
