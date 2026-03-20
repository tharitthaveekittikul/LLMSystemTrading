import { Badge } from "@/components/ui/badge";
import type { AgentField } from "./types";

export function FieldBadge({ field }: { field: AgentField }) {
  if (field.type === "shared") {
    return (
      <div className="flex items-start gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1">
        <span className="mt-0.5 text-amber-400 text-xs">⇢</span>
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-amber-300">{field.name}</span>
            {field.from && (
              <Badge
                variant="outline"
                className="border-amber-500/40 text-amber-400 text-[10px] px-1 py-0 h-auto"
              >
                from {field.from}
              </Badge>
            )}
          </div>
          {field.description && (
            <p className="text-[11px] text-muted-foreground">{field.description}</p>
          )}
        </div>
      </div>
    );
  }

  if (field.type === "output") {
    return (
      <div className="flex items-start gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1">
        <span className="mt-0.5 text-emerald-400 text-xs">→</span>
        <div>
          <span className="text-xs font-medium text-emerald-300">{field.name}</span>
          {field.description && (
            <p className="text-[11px] text-muted-foreground">{field.description}</p>
          )}
        </div>
      </div>
    );
  }

  if (field.type === "optional") {
    return (
      <div className="flex items-start gap-1.5 rounded-md border border-slate-600 bg-slate-800/50 px-2 py-1">
        <span className="mt-0.5 text-slate-500 text-xs">○</span>
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-slate-400">{field.name}</span>
            <Badge
              variant="outline"
              className="border-slate-600 text-slate-500 text-[10px] px-1 py-0 h-auto"
            >
              optional
            </Badge>
          </div>
          {field.description && (
            <p className="text-[11px] text-muted-foreground">{field.description}</p>
          )}
        </div>
      </div>
    );
  }

  // default: input
  return (
    <div className="flex items-start gap-1.5 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-1">
      <span className="mt-0.5 text-blue-400 text-xs">·</span>
      <div>
        <span className="text-xs text-blue-300">{field.name}</span>
        {field.description && (
          <p className="text-[11px] text-muted-foreground">{field.description}</p>
        )}
      </div>
    </div>
  );
}
