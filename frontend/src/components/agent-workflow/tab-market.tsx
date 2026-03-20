import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowRight, Zap } from "lucide-react";
import { AgentCard } from "./agent-card";
import { TransferArrow } from "./transfer-arrow";
import { FinalOutputBox } from "./final-output-box";
import { marketAgents } from "./agent-data";

export function TabMarket() {
  return (
    <div className="space-y-5 pt-4">
      {/* Description */}
      <div className="rounded-lg border bg-card/50 px-4 py-3">
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">Sequential 3-agent pipeline.</span>{" "}
          Agent 1 runs first. Its full output (
          <span className="text-amber-300 font-medium">market_context</span>) is forwarded to
          both Agent 2 and Agent 3. Agent 2 (optional — only when a chart image is provided)
          adds a{" "}
          <span className="text-amber-300 font-medium">visual_pattern</span> which Agent 3 also
          receives. A <span className="font-semibold text-foreground">confidence gate</span>{" "}
          at the end downgrades weak signals to HOLD.
        </p>
      </div>

      {/* Flow diagram */}
      <div className="overflow-x-auto pb-2">
        <div className="flex items-start min-w-max">
          <AgentCard agent={marketAgents[0]} />
          <TransferArrow fields={["market_context"]} />
          <AgentCard agent={marketAgents[1]} />
          <TransferArrow fields={["market_context", "visual_pattern"]} />
          <AgentCard agent={marketAgents[2]} />
          <div className="flex flex-col items-center justify-center px-2 self-center">
            <ArrowRight className="h-5 w-5 text-muted-foreground" />
          </div>
          <FinalOutputBox
            icon={Zap}
            title="TradingSignal"
            fields={["action", "entry", "SL/TP", "confidence", "rationale", "timeframe"]}
            gateNote="confidence gate: low → HOLD"
          />
        </div>
      </div>

      {/* Shared context breakdown */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardHeader className="pb-2 pt-3">
            <CardTitle className="text-sm text-amber-300">
              Shared: market_context (Agent 1 → 2 & 3)
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            <p className="mb-2">
              The full market analysis JSON is broadcast to both downstream agents — giving
              Chart Vision the context to interpret patterns correctly, and giving Execution
              Decision the foundational market picture it needs to pick entry/SL/TP.
            </p>
            <div className="flex flex-wrap gap-1">
              {[
                "trend",
                "trend_strength",
                "key_support",
                "key_resistance",
                "volatility",
                "context_notes",
              ].map((f) => (
                <Badge
                  key={f}
                  className="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[10px]"
                >
                  {f}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="border-purple-500/30 bg-purple-500/5">
          <CardHeader className="pb-2 pt-3">
            <CardTitle className="text-sm text-purple-300">
              Shared: visual_pattern (Agent 2 → 3, optional)
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            <p className="mb-2">
              Only flows when a chart image is provided. Gives Execution Decision a visual
              confirmation layer — pattern direction aligns (or conflicts) with the data-driven
              market_context, raising or lowering signal confidence.
            </p>
            <div className="flex flex-wrap gap-1">
              {["chart_pattern", "pattern_direction", "chart_notes"].map((f) => (
                <Badge
                  key={f}
                  className="bg-purple-500/10 border border-purple-500/30 text-purple-300 text-[10px]"
                >
                  {f}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Collaboration insight */}
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
        <p className="text-sm font-semibold text-emerald-300 mb-1">
          Why this collaboration works well
        </p>
        <ul className="text-xs text-muted-foreground space-y-1 list-disc list-inside">
          <li>
            Agent 1 acts as a{" "}
            <span className="text-foreground font-medium">shared context builder</span> — its
            output is the common ground for all downstream agents.
          </li>
          <li>
            Agent 3 benefits from{" "}
            <span className="text-foreground font-medium">two independent perspectives</span>:
            structured data analysis (Agent 1) + visual pattern recognition (Agent 2), reducing
            false signals.
          </li>
          <li>
            Each agent has a{" "}
            <span className="text-foreground font-medium">single, focused role</span> — market
            context, visual pattern, or execution — keeping prompts tight and outputs reliable.
          </li>
        </ul>
      </div>
    </div>
  );
}
