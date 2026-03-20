"use client"
import type { PipelineCombinationRow } from "@/types/trading"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { GitMerge } from "lucide-react"

interface Props {
  data: PipelineCombinationRow[]
}

function WinRateBadge({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100)
  const variant =
    pct >= 60 ? "default" : pct >= 45 ? "secondary" : "destructive"
  return <Badge variant={variant}>{pct}%</Badge>
}

function fmt(v: number, decimals = 2) {
  return v.toFixed(decimals)
}

export function PipelineCombinationsTable({ data }: Props) {
  if (!data.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <GitMerge className="h-4 w-4" />
            Pipeline Combinations
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No pipeline data yet.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <GitMerge className="h-4 w-4" />
          Pipeline Combinations
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Win rate reflects the full pipeline outcome — not individual model attribution.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Analysis Model</TableHead>
              <TableHead>Execution Model</TableHead>
              <TableHead className="text-right">Runs</TableHead>
              <TableHead className="text-right">Trades</TableHead>
              <TableHead className="text-right">Win Rate</TableHead>
              <TableHead className="text-right">Total P&amp;L</TableHead>
              <TableHead className="text-right">ROI / $</TableHead>
              <TableHead className="text-right">Analysis $</TableHead>
              <TableHead className="text-right">Execution $</TableHead>
              <TableHead className="text-right">Total Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((row) => (
              <TableRow key={row.pipeline_key}>
                <TableCell className="font-mono text-xs">{row.analysis_model}</TableCell>
                <TableCell className="font-mono text-xs">{row.execution_model}</TableCell>
                <TableCell className="text-right">{row.total_runs}</TableCell>
                <TableCell className="text-right">{row.trades_triggered}</TableCell>
                <TableCell className="text-right">
                  <WinRateBadge rate={row.win_rate} />
                </TableCell>
                <TableCell
                  className={`text-right font-medium ${
                    row.total_pnl_usd >= 0 ? "text-green-600" : "text-red-500"
                  }`}
                >
                  {row.total_pnl_usd >= 0 ? "+" : ""}
                  {fmt(row.total_pnl_usd)}
                </TableCell>
                <TableCell className="text-right">
                  {fmt(row.profit_per_dollar, 2)}x
                </TableCell>
                <TableCell className="text-right text-muted-foreground text-xs">
                  ${fmt(row.analysis_cost_usd, 4)}
                </TableCell>
                <TableCell className="text-right text-muted-foreground text-xs">
                  ${fmt(row.execution_cost_usd, 4)}
                </TableCell>
                <TableCell className="text-right text-xs">
                  ${fmt(row.total_cost_usd, 4)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
