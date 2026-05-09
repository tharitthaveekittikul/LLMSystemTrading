// ── Types ─────────────────────────────────────────────────────────────────────

export type FieldType = "input" | "output" | "shared" | "optional";

export interface AgentField {
  name: string;
  type: FieldType;
  description?: string;
  from?: string;
}

export interface AgentDef {
  id: string;
  name: string;
  role: string;
  color: "blue" | "purple" | "green" | "amber" | "rose" | "slate";
  inputs: AgentField[];
  outputs: AgentField[];
  optional?: boolean;
}

// ── Colour maps ───────────────────────────────────────────────────────────────

export const borderBg: Record<AgentDef["color"], string> = {
  blue:   "border-blue-400/60 bg-blue-50 dark:border-blue-500/50 dark:bg-blue-500/8",
  purple: "border-purple-400/60 bg-purple-50 dark:border-purple-500/50 dark:bg-purple-500/8",
  green:  "border-emerald-400/60 bg-emerald-50 dark:border-emerald-500/50 dark:bg-emerald-500/8",
  amber:  "border-amber-400/60 bg-amber-50 dark:border-amber-500/50 dark:bg-amber-500/8",
  rose:   "border-rose-400/60 bg-rose-50 dark:border-rose-500/50 dark:bg-rose-500/8",
  slate:  "border-slate-300 bg-slate-100 dark:border-slate-600 dark:bg-slate-800/30",
};

export const titleColor: Record<AgentDef["color"], string> = {
  blue:   "text-blue-600 dark:text-blue-400",
  purple: "text-purple-600 dark:text-purple-400",
  green:  "text-emerald-600 dark:text-emerald-400",
  amber:  "text-amber-600 dark:text-amber-400",
  rose:   "text-rose-600 dark:text-rose-400",
  slate:  "text-slate-600 dark:text-slate-400",
};
