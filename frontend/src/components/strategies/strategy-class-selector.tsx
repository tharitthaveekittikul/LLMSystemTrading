"use client";

import { Badge } from "@/components/ui/badge";
import type { StrategyRegistryEntry } from "@/types/trading";
import { cn } from "@/lib/utils";

const EXECUTION_MODE_LABEL: Record<string, string> = {
  rule_only: "Rule Only",
  rule_then_llm: "Rule + LLM",
  llm_only: "LLM Only",
  hybrid_validator: "Hybrid",
  multi_agent: "Multi-Agent",
};

const EXECUTION_MODE_COLOR: Record<string, string> = {
  rule_only: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
  rule_then_llm: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  llm_only: "bg-purple-500/10 text-purple-600 border-purple-500/20",
  hybrid_validator: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  multi_agent: "bg-rose-500/10 text-rose-600 border-rose-500/20",
};

interface Props {
  entries: StrategyRegistryEntry[];
  value: string | null;
  onChange: (key: string) => void;
}

export function StrategyClassSelector({ entries, value, onChange }: Props) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No registered strategies found.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      {entries.map((entry) => {
        const selected = value === entry.key;
        return (
          <button
            key={entry.key}
            type="button"
            onClick={() => onChange(entry.key)}
            className={cn(
              "flex flex-col gap-1.5 rounded-lg border p-4 text-left transition-colors",
              selected
                ? "border-primary bg-primary/5 ring-1 ring-primary"
                : "border-border bg-background hover:bg-muted/50"
            )}
          >
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{entry.display_name}</span>
              <Badge
                variant="outline"
                className={cn(
                  "text-xs font-normal",
                  EXECUTION_MODE_COLOR[entry.execution_mode] ?? ""
                )}
              >
                {EXECUTION_MODE_LABEL[entry.execution_mode] ?? entry.execution_mode}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {entry.description}
            </p>
            <p className="text-xs text-muted-foreground/60 font-mono">
              {entry.module_path}.{entry.class_name}
            </p>
          </button>
        );
      })}
    </div>
  );
}
