"use client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface PatternGroup {
  name: string; trades: number; win_rate: number; total_pnl: number
  avg_win: number; avg_loss: number; profit_factor: number; best_symbol: string
}

interface PatternGridPanelProps {
  groups: PatternGroup[]
}

const PATTERN_COLORS: Record<string, string> = {
  Shark: "border-purple-500",
  Gartley: "border-blue-500",
  Bat: "border-cyan-500",
  Butterfly: "border-pink-500",
  Crab: "border-orange-500",
  Cypher: "border-yellow-500",
  ABCD: "border-green-500",
}

export function PatternGridPanel({ groups }: PatternGridPanelProps) {
  if (!groups.length) {
    return <p className="text-muted-foreground text-sm">No pattern data available.</p>
  }

  return (
    <div>
      <h3 className="font-medium mb-3">Pattern Performance Overview</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {groups.map((g) => (
          <Card key={g.name} className={`border-l-4 ${PATTERN_COLORS[g.name] ?? "border-muted"}`}>
            <CardHeader className="pb-2 pt-3 px-3">
              <CardTitle className="text-base">{g.name}</CardTitle>
              <p className="text-xs text-muted-foreground">Best: {g.best_symbol}</p>
            </CardHeader>
            <CardContent className="px-3 pb-3 space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Trades</span>
                <span className="font-medium">{g.trades}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Win Rate</span>
                <span className={g.win_rate >= 0.5 ? "text-green-600 font-medium" : "text-red-500 font-medium"}>
                  {(g.win_rate * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Profit Factor</span>
                <span className="font-medium">{g.profit_factor.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total P&L</span>
                <span className={g.total_pnl >= 0 ? "text-green-600 font-medium" : "text-red-500 font-medium"}>
                  {g.total_pnl >= 0 ? "+" : ""}{g.total_pnl.toFixed(0)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Avg Win</span>
                <span className="text-green-600">{g.avg_win.toFixed(0)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Avg Loss</span>
                <span className="text-red-500">{g.avg_loss.toFixed(0)}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
