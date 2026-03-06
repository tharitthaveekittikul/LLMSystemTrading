import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { LLMPricingEntry } from "@/types/trading"

const PROVIDER_BADGE: Record<string, string> = {
  google:    "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  anthropic: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  openai:    "bg-green-500/15 text-green-700 dark:text-green-400",
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
                <span className="mx-2">·</span>
                <span>Out ${entry.output_per_1m_usd}/1M</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
