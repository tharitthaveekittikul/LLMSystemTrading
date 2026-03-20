import { ArrowRight, Brain, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { AgentCard } from "./agent-card";
import { newsGateAgent, economicEventAgent } from "./agent-data";

export function TabNews() {
  return (
    <div className="space-y-6 pt-4">

      {/* ── Pipeline A: News Impact Gate ── */}
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold">Pipeline A: News Impact Gate</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Lightweight pre-execution gate. Called before the Market Analysis pipeline is
            triggered. Its output (
            <span className="text-amber-300 font-medium">signal + reasoning</span>) is formatted
            into a{" "}
            <code className="rounded bg-muted px-1 text-xs">news_context</code> string and
            passed as an optional input into{" "}
            <span className="font-medium text-foreground">Agent 1 (Market Analysis)</span>. If
            no high-impact events are found, the gate returns HOLD and Market Analysis runs
            without news context.
          </p>
        </div>

        <div className="flex items-start gap-3 flex-wrap">
          <AgentCard agent={newsGateAgent} />
          <div className="flex flex-col items-center justify-center gap-1 px-2 self-center">
            <Badge className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px]">
              news_context string
            </Badge>
            <ArrowRight className="h-5 w-5 text-amber-400" />
          </div>
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-blue-500/40 bg-blue-500/5 p-4 w-[220px] self-center">
            <Brain className="h-5 w-5 text-blue-400 mb-1.5" />
            <p className="text-xs font-semibold text-blue-300">Market Analysis Pipeline</p>
            <p className="text-[11px] text-muted-foreground mt-1 text-center">
              Receives <code className="bg-muted px-0.5 rounded">news_context</code> as an
              optional input to Agent 1
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
          <p className="text-sm font-semibold text-emerald-300 mb-1">Collaboration insight</p>
          <p className="text-xs text-muted-foreground">
            This is the{" "}
            <span className="text-foreground font-medium">only cross-pipeline context link</span>
            . The News Gate&apos;s output is the bridge between the News and Market Analysis
            pipelines. It gives Agent 1 macro awareness without adding complexity to the main
            pipeline — Agent 1 simply includes or skips the news section based on whether the
            string is present.
          </p>
        </div>
      </div>

      <div className="border-t border-border" />

      {/* ── Pipeline B: Economic Event Analysis ── */}
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold">
            Pipeline B: Economic Event Analysis (ForexFactory)
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Standalone pipeline. Runs daily at{" "}
            <code className="rounded bg-muted px-1 text-xs">00:00 UTC</code> via scheduler, or
            triggered manually from the News page. Results are stored back into the{" "}
            <code className="rounded bg-muted px-1 text-xs">economic_events</code> DB table.{" "}
            <span className="text-amber-300 font-medium">
              No context is shared with other agents
            </span>{" "}
            — this pipeline is self-contained.
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-slate-600 bg-slate-800/30 p-4 w-[200px]">
            <Database className="h-5 w-5 text-slate-400 mb-1.5" />
            <p className="text-xs font-semibold text-slate-300">ForexFactory Events</p>
            <p className="text-[10px] text-muted-foreground mt-1 text-center">
              Fetched daily from ForexFactory RSS → stored in economic_events table
            </p>
          </div>
          <ArrowRight className="h-5 w-5 text-muted-foreground" />
          <AgentCard agent={economicEventAgent} />
          <ArrowRight className="h-5 w-5 text-muted-foreground" />
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-slate-600 bg-slate-800/30 p-4 w-[200px]">
            <Database className="h-5 w-5 text-slate-400 mb-1.5" />
            <p className="text-xs font-semibold text-slate-300">Results → DB</p>
            <div className="mt-2 flex flex-wrap justify-center gap-1">
              {["llm_signal", "llm_summary", "affected_symbols_detail"].map((f) => (
                <Badge
                  key={f}
                  className="bg-slate-800 border border-slate-600 text-slate-400 text-[10px]"
                >
                  {f}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
