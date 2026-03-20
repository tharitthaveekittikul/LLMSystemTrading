import { Badge } from "@/components/ui/badge";
import { Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import { borderBg, titleColor } from "./types";
import type { AgentDef } from "./types";
import { FieldBadge } from "./field-badge";

export function AgentCard({ agent }: { agent: AgentDef }) {
  return (
    <div
      className={cn(
        "rounded-xl border-2 p-4 w-[280px] shrink-0",
        borderBg[agent.color]
      )}
    >
      <div className="mb-3">
        <div className="flex items-center gap-2">
          <Brain className={cn("h-4 w-4 shrink-0", titleColor[agent.color])} />
          <span className={cn("text-sm font-semibold", titleColor[agent.color])}>
            {agent.name}
          </span>
          {agent.optional && (
            <Badge
              variant="outline"
              className="border-slate-600 text-slate-500 text-[10px] px-1 py-0 h-auto"
            >
              optional
            </Badge>
          )}
        </div>
        <p className="mt-0.5 ml-6 text-[11px] text-muted-foreground">{agent.role}</p>
      </div>

      <div className="space-y-3">
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Inputs
          </p>
          <div className="space-y-1">
            {agent.inputs.map((f, i) => (
              <FieldBadge key={i} field={f} />
            ))}
          </div>
        </div>

        <div className="border-t border-border/50 pt-2">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Outputs
          </p>
          <div className="space-y-1">
            {agent.outputs.map((f, i) => (
              <FieldBadge key={i} field={f} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
