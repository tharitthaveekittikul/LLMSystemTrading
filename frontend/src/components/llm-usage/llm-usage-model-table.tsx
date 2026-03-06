"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { LLMModelUsage } from "@/types/trading"

const PROVIDER_BADGE: Record<string, string> = {
  google:    "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/20",
  anthropic: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  openai:    "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
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
        <p className="text-xs text-muted-foreground">Token usage and cost per model</p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow className="text-xs">
              <TableHead className="pl-4">Model</TableHead>
              <TableHead className="text-right">Calls</TableHead>
              <TableHead className="text-right text-muted-foreground">Input</TableHead>
              <TableHead className="text-right text-muted-foreground">Output</TableHead>
              <TableHead className="text-right">Total Tokens</TableHead>
              <TableHead className="text-right pr-4">Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No LLM calls recorded yet
                </TableCell>
              </TableRow>
            ) : (
              data.map(row => (
                <TableRow key={row.model}>
                  <TableCell className="pl-4">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={`text-xs ${PROVIDER_BADGE[row.provider] ?? ""}`}
                      >
                        {row.provider}
                      </Badge>
                      <span className="font-mono text-xs">{row.model}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{row.calls}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {fmtTokens(row.input_tokens)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {fmtTokens(row.output_tokens)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-medium">
                    {fmtTokens(row.total_tokens)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-semibold pr-4">
                    {fmtCost(row.cost_usd)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
