import { Badge } from "@/components/ui/badge";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

const contextLinks = [
  {
    from: "News Gate",
    to: "Market Analysis Agent 1",
    field: "news_context",
    note: "Cross-pipeline: only link between news and trading pipelines",
    color: "amber",
  },
  {
    from: "Market Analysis Agent 1",
    to: "Chart Vision Agent 2",
    field: "market_context",
    note: "Gives visual agent the data context to interpret chart patterns accurately",
    color: "amber",
  },
  {
    from: "Market Analysis Agent 1",
    to: "Execution Decision Agent 3",
    field: "market_context",
    note: "Core foundation for the final trade decision",
    color: "amber",
  },
  {
    from: "Chart Vision Agent 2",
    to: "Execution Decision Agent 3",
    field: "visual_pattern",
    note: "Visual confirmation layer — optional but improves signal quality",
    color: "purple",
  },
  {
    from: "Technical Analysis Agent 1a",
    to: "Maintenance Decision Agent 2",
    field: "technical_output",
    note: "Quantified technical score drives MODIFY vs HOLD logic",
    color: "blue",
  },
  {
    from: "Sentiment Analysis Agent 1b",
    to: "Maintenance Decision Agent 2",
    field: "sentiment_output",
    note: "Macro context prevents holding through high-risk events",
    color: "amber",
  },
  // ── RAG Feedback Loop ──────────────────────────────────────────────────────
  {
    from: "Post-Trade Analyzer",
    to: "DB (trades.trade_analysis)",
    field: "trade_analysis JSON",
    note: "Fires after every close — stores correct/wrong signals, lesson, confidence_justified",
    color: "teal",
  },
  {
    from: "Research Loop",
    to: "research_config.json",
    field: "lessons + blocked_symbols",
    note: "Runs every 30 trades — LLM reviews 90-day stats and writes actionable lessons",
    color: "violet",
  },
  {
    from: "RAG Context Builder",
    to: "Market Analysis Agent 1",
    field: "rag_context",
    note: "8-section SQL-aggregated performance history — no LLM cost, injected before every call",
    color: "orange",
  },
  {
    from: "RAG Context Builder",
    to: "Maintenance Agents 1a + 1b",
    field: "rag_context",
    note: "Same performance context injected into both maintenance agents on every run",
    color: "orange",
  },
] as const;

export function ContextMap() {
  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <h2 className="text-sm font-semibold">System-wide Context Flow Summary</h2>
      <div className="grid grid-cols-1 gap-2 text-xs md:grid-cols-2 lg:grid-cols-3">
        {contextLinks.map((item, i) => (
          <div key={i} className="rounded-md border bg-card/50 p-3 space-y-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-muted-foreground">{item.from}</span>
              <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
              <span className="text-foreground font-medium">{item.to}</span>
            </div>
            <Badge
              className={cn(
                "text-[10px]",
                item.color === "amber"
                  ? "bg-amber-500/10 border border-amber-500/30 text-amber-300"
                  : item.color === "purple"
                  ? "bg-purple-500/10 border border-purple-500/30 text-purple-300"
                  : item.color === "teal"
                  ? "bg-teal-500/10 border border-teal-500/30 text-teal-300"
                  : item.color === "violet"
                  ? "bg-violet-500/10 border border-violet-500/30 text-violet-300"
                  : item.color === "orange"
                  ? "bg-orange-500/10 border border-orange-500/30 text-orange-300"
                  : "bg-blue-500/10 border border-blue-500/30 text-blue-300"
              )}
            >
              {item.field}
            </Badge>
            <p className="text-[11px] text-muted-foreground">{item.note}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
