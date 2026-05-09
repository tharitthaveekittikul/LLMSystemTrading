import { Badge } from "@/components/ui/badge";
import type { AgentField } from "./types";

export function FieldBadge({ field }: { field: AgentField }) {
  if (field.type === "shared") {
    return (
      <div className="flex items-start gap-1.5 rounded-md border border-amber-400/50 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10 px-2 py-1">
        <span className="mt-0.5 text-amber-600 dark:text-amber-400 text-xs">⇢</span>
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-amber-700 dark:text-amber-300">{field.name}</span>
            {field.from && (
              <Badge
                variant="outline"
                className="border-amber-400/50 text-amber-600 dark:border-amber-500/40 dark:text-amber-400 text-[10px] px-1 py-0 h-auto"
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
      <div className="flex items-start gap-1.5 rounded-md border border-emerald-400/50 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10 px-2 py-1">
        <span className="mt-0.5 text-emerald-600 dark:text-emerald-400 text-xs">→</span>
        <div>
          <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">{field.name}</span>
          {field.description && (
            <p className="text-[11px] text-muted-foreground">{field.description}</p>
          )}
        </div>
      </div>
    );
  }

  if (field.type === "optional") {
    return (
      <div className="flex items-start gap-1.5 rounded-md border border-slate-300 bg-slate-100 dark:border-slate-600 dark:bg-slate-800/50 px-2 py-1">
        <span className="mt-0.5 text-slate-500 dark:text-slate-500 text-xs">○</span>
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-slate-600 dark:text-slate-400">{field.name}</span>
            <Badge
              variant="outline"
              className="border-slate-300 text-slate-500 dark:border-slate-600 dark:text-slate-500 text-[10px] px-1 py-0 h-auto"
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
    <div className="flex items-start gap-1.5 rounded-md border border-blue-400/50 bg-blue-50 dark:border-blue-500/30 dark:bg-blue-500/10 px-2 py-1">
      <span className="mt-0.5 text-blue-600 dark:text-blue-400 text-xs">·</span>
      <div>
        <span className="text-xs text-blue-700 dark:text-blue-300">{field.name}</span>
        {field.description && (
          <p className="text-[11px] text-muted-foreground">{field.description}</p>
        )}
      </div>
    </div>
  );
}
