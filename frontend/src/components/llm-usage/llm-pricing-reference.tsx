import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { LLMPricingEntry } from "@/types/trading"

const PROVIDER_BADGE: Record<string, string> = {
  google:    "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/20",
  anthropic: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  openai:    "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
}

interface PricingReferenceProps {
  data: LLMPricingEntry[]
}

export function LLMPricingReference({ data }: PricingReferenceProps) {
  const relevant = data.filter(d => d.input_per_1m_usd != null)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Model Pricing Reference</CardTitle>
        <p className="text-xs text-muted-foreground">Cost per 1M tokens for each model</p>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y">
          {relevant.map(entry => (
            <div key={entry.model} className="flex items-center justify-between px-4 py-2.5">
              <div className="flex items-center gap-2">
                <Badge
                  variant="outline"
                  className={`text-xs ${PROVIDER_BADGE[entry.provider] ?? ""}`}
                >
                  {entry.provider}
                </Badge>
                <span className="font-mono text-xs">{entry.model}</span>
              </div>
              <div className="text-xs text-muted-foreground text-right">
                <span>In ${entry.input_per_1m_usd}/1M</span>
                <span className="mx-2 opacity-40">·</span>
                <span>Out ${entry.output_per_1m_usd}/1M</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
