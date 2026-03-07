"use client"

interface Combo {
  symbol: string; pattern: string; trades: number
  win_rate: number; total_pnl: number; profit_factor: number
}

interface CombinationsProps {
  top: Combo[]; worst: Combo[]; recommendations: string[]
}

function ComboRow({ combo }: { combo: Combo }) {
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-2 font-medium">{combo.symbol}</td>
      <td className="py-2 pr-2 text-muted-foreground">{combo.pattern}</td>
      <td className="py-2 pr-2 text-right">{combo.trades}</td>
      <td className="py-2 pr-2 text-right">
        <span className={combo.win_rate >= 0.5 ? "text-green-600" : "text-red-500"}>
          {(combo.win_rate * 100).toFixed(0)}%
        </span>
      </td>
      <td className="py-2 text-right">
        <span className={combo.total_pnl >= 0 ? "text-green-600" : "text-red-500"}>
          {combo.total_pnl >= 0 ? "+" : ""}{combo.total_pnl.toFixed(0)}
        </span>
      </td>
    </tr>
  )
}

export function AnalyticsCombinations({ top, worst, recommendations }: CombinationsProps) {
  const headers = ["Symbol", "Pattern", "Trades", "Win Rate", "P&L"]
  return (
    <div className="space-y-4">
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <h3 className="font-medium mb-2 text-green-700 dark:text-green-400">Top 10 Combinations</h3>
          <table className="text-sm w-full">
            <thead><tr>{headers.map(h => <th key={h} className="text-left py-1 pr-2 text-muted-foreground font-normal text-xs">{h}</th>)}</tr></thead>
            <tbody>{top.map((c, i) => <ComboRow key={i} combo={c} />)}</tbody>
          </table>
        </div>
        <div>
          <h3 className="font-medium mb-2 text-red-700 dark:text-red-400">Worst 10 Combinations</h3>
          <table className="text-sm w-full">
            <thead><tr>{headers.map(h => <th key={h} className="text-left py-1 pr-2 text-muted-foreground font-normal text-xs">{h}</th>)}</tr></thead>
            <tbody>{worst.map((c, i) => <ComboRow key={i} combo={c} />)}</tbody>
          </table>
        </div>
      </div>
      {recommendations.length > 0 && (
        <div>
          <h3 className="font-medium mb-2">Recommendations</h3>
          <div className="space-y-1">
            {recommendations.map((r, i) => (
              <p key={i} className="text-sm text-muted-foreground bg-muted/50 rounded px-3 py-2">{r}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
