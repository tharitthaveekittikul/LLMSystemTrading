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
  blue:   "border-blue-500/50 bg-blue-500/5",
  purple: "border-purple-500/50 bg-purple-500/5",
  green:  "border-emerald-500/50 bg-emerald-500/5",
  amber:  "border-amber-500/50 bg-amber-500/5",
  rose:   "border-rose-500/50 bg-rose-500/5",
  slate:  "border-slate-600 bg-slate-800/30",
};

export const titleColor: Record<AgentDef["color"], string> = {
  blue:   "text-blue-400",
  purple: "text-purple-400",
  green:  "text-emerald-400",
  amber:  "text-amber-400",
  rose:   "text-rose-400",
  slate:  "text-slate-400",
};
