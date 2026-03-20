import { ArrowDown, GitMerge, Shield } from "lucide-react";
import { AgentCard } from "./agent-card";
import { TransferArrow } from "./transfer-arrow";
import { FinalOutputBox } from "./final-output-box";
import { maintenanceAgents } from "./agent-data";

export function TabMaintenance() {
  return (
    <div className="space-y-5 pt-4">
      {/* Description */}
      <div className="rounded-lg border bg-card/50 px-4 py-3">
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">Fan-in pipeline.</span>{" "}
          Agents 1a and 1b run{" "}
          <span className="font-medium text-foreground">independently in parallel</span> — they
          do not share context with each other. Both outputs are then passed together to Agent 2
          (Decision) as{" "}
          <span className="text-amber-300 font-medium">technical_output</span> and{" "}
          <span className="text-amber-300 font-medium">sentiment_output</span>, which it uses to
          produce a HOLD / CLOSE / MODIFY recommendation.
        </p>
      </div>

      {/* Fan-in diagram */}
      <div className="flex flex-col items-center gap-0">
        {/* Parallel agents */}
        <div className="flex items-start gap-6">
          <AgentCard agent={maintenanceAgents[0]} />
          <AgentCard agent={maintenanceAgents[1]} />
        </div>

        {/* Down arrows */}
        <div className="flex gap-6">
          <div style={{ width: 280 }} className="flex justify-center">
            <TransferArrow fields={["technical_output"]} direction="down" />
          </div>
          <div style={{ width: 280 }} className="flex justify-center">
            <TransferArrow fields={["sentiment_output"]} direction="down" />
          </div>
        </div>

        {/* Merge node */}
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2 mb-1">
          <GitMerge className="h-4 w-4 text-amber-400" />
          <span className="text-xs text-amber-300">
            Both outputs merged as inputs to Decision agent
          </span>
        </div>
        <ArrowDown className="h-5 w-5 text-amber-400" />

        {/* Decision agent */}
        <div className="mt-0">
          <AgentCard agent={maintenanceAgents[2]} />
        </div>

        {/* Final output */}
        <ArrowDown className="h-5 w-5 text-muted-foreground mt-1" />
        <FinalOutputBox
          icon={Shield}
          title="MaintenanceDecision"
          fields={["HOLD", "CLOSE", "MODIFY", "new_sl/tp", "confidence", "rationale"]}
          gateNote="confidence gate: low → HOLD"
        />
      </div>

      {/* Collaboration insight */}
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
        <p className="text-sm font-semibold text-emerald-300 mb-1">
          Why this collaboration works well
        </p>
        <ul className="text-xs text-muted-foreground space-y-1 list-disc list-inside">
          <li>
            Technical and Sentiment agents are{" "}
            <span className="text-foreground font-medium">independent specialists</span> —
            neither biases the other&apos;s analysis, so their outputs are genuinely
            complementary.
          </li>
          <li>
            The Decision agent is a{" "}
            <span className="text-foreground font-medium">neutral aggregator</span>: it
            synthesises two scores (technical_score + sentiment_score) into one actionable
            recommendation, reducing the chance of one-dimensional signals.
          </li>
          <li>
            Closing or modifying a live trade requires{" "}
            <span className="text-foreground font-medium">
              both technical and macro confirmation
            </span>{" "}
            — this structure enforces that discipline systematically.
          </li>
        </ul>
      </div>
    </div>
  );
}
