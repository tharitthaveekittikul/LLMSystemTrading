"use client"
import { useState } from "react"
import { ArrowUpDown } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { SymbolPnLRow } from "@/types/trading"

interface Props {
  data: SymbolPnLRow[]
  groupBy: "symbol" | "source"
  onGroupByChange: (g: "symbol" | "source") => void
}

type SortKey = keyof SymbolPnLRow
type SortDir = "asc" | "desc"

function pnlClass(value: number): string {
  if (value > 0) return "text-green-600"
  if (value < 0) return "text-red-600"
  return ""
}

export function SymbolPnLTable({ data, groupBy, onGroupByChange }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("net_pnl_usd")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey]
    const bv = b[sortKey]
    if (typeof av === "string" || typeof bv === "string") {
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av))
    }
    return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number)
  })

  const cols: { key: SortKey; label: string; fmt: (r: SymbolPnLRow) => string; cls?: (r: SymbolPnLRow) => string }[] = [
    { key: "trade_count", label: "AI Trades", fmt: r => r.trade_count.toString() },
    { key: "realized_pnl_usd", label: "Realized P&L", fmt: r => `$${r.realized_pnl_usd.toFixed(2)}`, cls: r => pnlClass(r.realized_pnl_usd) },
    { key: "attributed_llm_cost_usd", label: "LLM Cost", fmt: r => `$${r.attributed_llm_cost_usd.toFixed(5)}` },
    { key: "net_pnl_usd", label: "Net P&L", fmt: r => `$${r.net_pnl_usd.toFixed(2)}`, cls: r => pnlClass(r.net_pnl_usd) },
    { key: "manual_trade_count", label: "Manual Trades", fmt: r => r.manual_trade_count.toString() },
    { key: "manual_pnl_usd", label: "Manual P&L", fmt: r => r.manual_trade_count > 0 ? `$${r.manual_pnl_usd.toFixed(2)}` : "—", cls: r => r.manual_trade_count > 0 ? pnlClass(r.manual_pnl_usd) : "" },
  ]

  const groupLabel = groupBy === "symbol" ? "Symbol" : "Strategy / Source"

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Net P&L After LLM Cost</CardTitle>
        <div className="flex rounded-md border overflow-hidden text-xs">
          {(["symbol", "source"] as const).map(g => (
            <button
              key={g}
              onClick={() => onGroupByChange(g)}
              className={`px-3 py-1 transition-colors ${
                groupBy === g ? "bg-primary text-primary-foreground" : "hover:bg-muted"
              }`}
            >
              {g === "symbol" ? "By Symbol" : "By Strategy"}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {!data.length ? (
          <div className="h-24 flex items-center justify-center text-muted-foreground text-sm">No data</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">{groupLabel}</th>
                  {cols.map(c => (
                    <th
                      key={c.key}
                      className="text-right px-3 py-2 font-medium text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                      onClick={() => handleSort(c.key)}
                    >
                      <span className="inline-flex items-center gap-1">
                        {c.label}
                        <ArrowUpDown className="h-3 w-3" />
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map(row => (
                  <tr key={row.group} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2 font-medium truncate max-w-[200px]" title={row.group}>
                      {row.group}
                    </td>
                    {cols.map(c => (
                      <td
                        key={c.key}
                        className={`px-3 py-2 text-right tabular-nums ${c.cls ? c.cls(row) : ""}`}
                      >
                        {c.fmt(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
