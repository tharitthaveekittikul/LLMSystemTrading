"use client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { LLMHeatmapResponse } from "@/types/trading"

interface Props {
  data: LLMHeatmapResponse | null
}

function cellColor(value: number | null): string {
  if (value === null) return "bg-muted text-muted-foreground"
  if (value >= 0.6) return "bg-green-600 text-white"
  if (value >= 0.5) return "bg-green-400"
  if (value >= 0.4) return "bg-yellow-400"
  return "bg-red-400 text-white"
}

export function ModelSymbolHeatmap({ data }: Props) {
  if (!data || !data.models.length) {
    return (
      <Card className="h-full">
        <CardHeader><CardTitle className="text-base">Win Rate: Model × Symbol</CardTitle></CardHeader>
        <CardContent>
          <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">No data</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full">
      <CardHeader><CardTitle className="text-base">Win Rate: Model × Symbol</CardTitle></CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="text-xs border-collapse w-full">
            <thead>
              <tr>
                <th className="p-1 text-left text-muted-foreground font-normal">Model ↓ / Symbol →</th>
                {data.symbols.map(s => (
                  <th key={s} className="p-1 text-center font-normal text-muted-foreground">{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.models.map((model, mi) => (
                <tr key={model}>
                  <td className="p-1 font-medium truncate max-w-[140px]" title={model}>{model}</td>
                  {data.symbols.map((_, si) => {
                    const val = data.values[mi]?.[si] ?? null
                    return (
                      <td key={si} className={`p-1 text-center rounded ${cellColor(val)}`}>
                        {val !== null ? `${(val * 100).toFixed(0)}%` : "—"}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-600 inline-block"/>≥60%</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-400 inline-block"/>≥50%</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-yellow-400 inline-block"/>≥40%</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-400 inline-block"/>&lt;40%</span>
        </div>
      </CardContent>
    </Card>
  )
}
