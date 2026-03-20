"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ArrowRight,
  ArrowDown,
  Brain,
  Database,
  GitMerge,
  Newspaper,
  Network,
  Shield,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type FieldType = "input" | "output" | "shared" | "optional";

interface AgentField {
  name: string;
  type: FieldType;
  description?: string;
  from?: string;
}

interface AgentDef {
  id: string;
  name: string;
  role: string;
  color: "blue" | "purple" | "green" | "amber" | "rose" | "slate";
  inputs: AgentField[];
  outputs: AgentField[];
  optional?: boolean;
}

// ── Colour maps ───────────────────────────────────────────────────────────────

const borderBg: Record<AgentDef["color"], string> = {
  blue:   "border-blue-500/50 bg-blue-500/5",
  purple: "border-purple-500/50 bg-purple-500/5",
  green:  "border-emerald-500/50 bg-emerald-500/5",
  amber:  "border-amber-500/50 bg-amber-500/5",
  rose:   "border-rose-500/50 bg-rose-500/5",
  slate:  "border-slate-600 bg-slate-800/30",
};

const titleColor: Record<AgentDef["color"], string> = {
  blue:   "text-blue-400",
  purple: "text-purple-400",
  green:  "text-emerald-400",
  amber:  "text-amber-400",
  rose:   "text-rose-400",
  slate:  "text-slate-400",
};

// ── Field Badge ───────────────────────────────────────────────────────────────

function FieldBadge({ field }: { field: AgentField }) {
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

// ── Agent Card ────────────────────────────────────────────────────────────────

function AgentCard({ agent }: { agent: AgentDef }) {
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

// ── Transfer Arrow ────────────────────────────────────────────────────────────

function TransferArrow({
  fields,
  direction = "right",
}: {
  fields: string[];
  direction?: "right" | "down";
}) {
  if (direction === "down") {
    return (
      <div className="flex flex-col items-center gap-1 py-2">
        <div className="flex flex-col items-center gap-1">
          {fields.map((f, i) => (
            <Badge
              key={i}
              className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px]"
            >
              {f}
            </Badge>
          ))}
        </div>
        <ArrowDown className="h-5 w-5 text-amber-400" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center gap-1 px-2 self-center">
      <div className="flex flex-wrap items-center justify-center gap-1">
        {fields.map((f, i) => (
          <Badge
            key={i}
            className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px]"
          >
            {f}
          </Badge>
        ))}
      </div>
      <ArrowRight className="h-5 w-5 text-amber-400" />
    </div>
  );
}

// ── Final Output Box ──────────────────────────────────────────────────────────

function FinalOutputBox({
  icon: Icon,
  title,
  fields,
  gateNote,
}: {
  icon: React.ElementType;
  title: string;
  fields: string[];
  gateNote?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border-2 border-emerald-500/60 bg-emerald-500/10 p-4 w-[200px] shrink-0">
      <Icon className="h-5 w-5 text-emerald-400 mb-1.5" />
      <p className="text-xs font-semibold text-emerald-300 text-center">{title}</p>
      <div className="mt-2 flex flex-wrap justify-center gap-1">
        {fields.map((f) => (
          <Badge
            key={f}
            className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[10px]"
          >
            {f}
          </Badge>
        ))}
      </div>
      {gateNote && (
        <div className="mt-2 rounded border border-emerald-500/30 bg-emerald-900/30 px-2 py-1 text-center">
          <p className="text-[10px] text-emerald-400">{gateNote}</p>
        </div>
      )}
    </div>
  );
}

// ── Agent Data ────────────────────────────────────────────────────────────────

const marketAgents: AgentDef[] = [
  {
    id: "market_analysis",
    name: "1. Market Analysis",
    role: "Assess market conditions & trend",
    color: "blue",
    inputs: [
      { name: "symbol + timeframe", type: "input" },
      { name: "current_price", type: "input" },
      { name: "indicators (RSI, MACD…)", type: "input" },
      { name: "OHLCV — last 20 candles", type: "input" },
      { name: "context_tfs OHLCV", type: "optional", description: "Higher-timeframe candles" },
      { name: "open_positions", type: "input" },
      { name: "recent_signals", type: "input" },
      { name: "news_context", type: "optional", description: "Pre-formatted news string from News Gate" },
      { name: "trade_history_context", type: "optional" },
    ],
    outputs: [
      { name: "trend (bullish/bearish/ranging)", type: "output" },
      { name: "trend_strength (0–1)", type: "output" },
      { name: "key_support / key_resistance", type: "output" },
      { name: "volatility (low/medium/high)", type: "output" },
      { name: "context_notes", type: "output" },
    ],
  },
  {
    id: "chart_vision",
    name: "2. Chart Vision",
    role: "Identify visual price patterns",
    color: "purple",
    optional: true,
    inputs: [
      { name: "symbol + timeframe", type: "input" },
      { name: "chart_image (base64 PNG)", type: "input" },
      {
        name: "market_context",
        type: "shared",
        from: "Agent 1",
        description: "trend, support/resistance, volatility, notes",
      },
    ],
    outputs: [
      { name: "chart_pattern (e.g. head_shoulders)", type: "output" },
      { name: "pattern_direction (bullish/bearish)", type: "output" },
      { name: "chart_notes", type: "output" },
    ],
  },
  {
    id: "execution_decision",
    name: "3. Execution Decision",
    role: "Final trade execution decision",
    color: "green",
    inputs: [
      { name: "symbol + timeframe + current_price", type: "input" },
      { name: "open_positions + recent_signals", type: "input" },
      {
        name: "market_context",
        type: "shared",
        from: "Agent 1",
        description: "trend, strength, support/resistance, volatility, notes",
      },
      {
        name: "visual_pattern",
        type: "shared",
        from: "Agent 2 (opt.)",
        description: "chart_pattern, direction, chart_notes",
      },
    ],
    outputs: [
      { name: "action (BUY/SELL/HOLD/LIMIT/STOP)", type: "output" },
      { name: "entry price", type: "output" },
      { name: "stop_loss / take_profit", type: "output" },
      { name: "confidence (0–1)", type: "output" },
      { name: "rationale", type: "output" },
    ],
  },
];

const maintenanceAgents: AgentDef[] = [
  {
    id: "technical",
    name: "1a. Technical Analysis",
    role: "Assess position's technical merit",
    color: "blue",
    inputs: [
      { name: "symbol + timeframe", type: "input" },
      { name: "OHLCV — last 20 candles", type: "input" },
      { name: "indicators", type: "input" },
      {
        name: "position state",
        type: "input",
        description: "ticket, direction, entry, SL, TP, PnL, volume",
      },
      { name: "strategy_params", type: "input", description: "sl_pips, tp_pips, risk_pct" },
    ],
    outputs: [
      { name: "trend + trend_strength", type: "output" },
      { name: "position_alignment", type: "output", description: "aligned | misaligned | neutral" },
      { name: "technical_score (–1 to 1)", type: "output" },
      { name: "notes", type: "output" },
    ],
  },
  {
    id: "sentiment",
    name: "1b. Sentiment Analysis",
    role: "Assess news sentiment for symbol",
    color: "amber",
    inputs: [
      { name: "symbol", type: "input" },
      { name: "news_context", type: "optional", description: "Upcoming events string" },
      { name: "trade_history_context", type: "optional" },
    ],
    outputs: [
      { name: "sentiment_direction (BULLISH/BEARISH/NEUTRAL)", type: "output" },
      { name: "event_risk (HIGH/MEDIUM/LOW)", type: "output" },
      { name: "key_events[]", type: "output" },
      { name: "sentiment_score (–1 to 1)", type: "output" },
      { name: "notes", type: "output" },
    ],
  },
  {
    id: "decision",
    name: "2. Maintenance Decision",
    role: "Final HOLD / CLOSE / MODIFY decision",
    color: "green",
    inputs: [
      { name: "symbol + position state", type: "input" },
      { name: "strategy_params", type: "input" },
      {
        name: "technical_output",
        type: "shared",
        from: "Agent 1a",
        description: "trend, alignment, technical_score, notes",
      },
      {
        name: "sentiment_output",
        type: "shared",
        from: "Agent 1b",
        description: "direction, event_risk, key_events, score",
      },
    ],
    outputs: [
      { name: "action (HOLD/CLOSE/MODIFY)", type: "output" },
      { name: "new_sl / new_tp", type: "output", description: "Only for MODIFY action" },
      { name: "confidence (0–1)", type: "output" },
      { name: "rationale", type: "output" },
    ],
  },
];

const newsGateAgent: AgentDef = {
  id: "news_gate",
  name: "News Impact Gate",
  role: "Pre-execution gate — predict price direction from upcoming events",
  color: "rose",
  inputs: [
    { name: "symbol", type: "input" },
    {
      name: "upcoming_events[]",
      type: "input",
      description: "currency, title, forecast, previous, time",
    },
  ],
  outputs: [
    { name: "signal (BUY/SELL/HOLD)", type: "output" },
    { name: "reasoning", type: "output" },
  ],
};

const economicEventAgent: AgentDef = {
  id: "econ_event",
  name: "Economic Event Analyst",
  role: "ForexFactory event pre-analysis (daily scheduler)",
  color: "purple",
  inputs: [
    { name: "event title + currency + impact", type: "input" },
    { name: "scheduled_time", type: "input" },
    { name: "forecast", type: "optional" },
    { name: "previous", type: "optional" },
    { name: "affected_symbols[]", type: "input" },
  ],
  outputs: [
    { name: "signal (BUY/SELL/HOLD/AVOID)", type: "output" },
    { name: "summary (2–3 sentences)", type: "output" },
    { name: "affected_symbols_detail", type: "output", description: "Per-symbol brief reason" },
  ],
};

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentWorkflowPage() {
  return (
    <div className="container mx-auto max-w-7xl space-y-6 p-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Network className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold">Agent Collaboration Workflows</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          How LLM agents collaborate — what context each agent receives, produces, and shares with
          others. Amber items{" "}
          <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1 text-amber-300">
            ⇢ shared
          </span>{" "}
          are outputs from one agent passed directly as inputs to the next.
        </p>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-xs">
        <span className="font-semibold text-muted-foreground mr-1">Legend:</span>
        <div className="flex items-center gap-1 rounded border border-blue-500/40 bg-blue-500/10 px-2 py-0.5">
          <span className="text-blue-400">·</span>
          <span className="text-blue-300">Input</span>
        </div>
        <div className="flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5">
          <span className="text-emerald-400">→</span>
          <span className="text-emerald-300">Output</span>
        </div>
        <div className="flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5">
          <span className="text-amber-400">⇢</span>
          <span className="text-amber-300">Shared context (from another agent)</span>
        </div>
        <div className="flex items-center gap-1 rounded border border-slate-600 bg-slate-800/50 px-2 py-0.5">
          <span className="text-slate-400">○</span>
          <span className="text-slate-400">Optional input</span>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="market">
        <TabsList>
          <TabsTrigger value="market" className="gap-2">
            <Brain className="h-4 w-4" />
            Market Analysis
          </TabsTrigger>
          <TabsTrigger value="maintenance" className="gap-2">
            <Shield className="h-4 w-4" />
            Position Maintenance
          </TabsTrigger>
          <TabsTrigger value="news" className="gap-2">
            <Newspaper className="h-4 w-4" />
            News Pipelines
          </TabsTrigger>
        </TabsList>

        {/* ── Tab 1: Market Analysis ───────────────────────────────────────────── */}
        <TabsContent value="market" className="space-y-5 pt-4">
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
                Agent 1 acts as a <span className="text-foreground font-medium">shared context builder</span> — its output is the common ground for all downstream agents.
              </li>
              <li>
                Agent 3 benefits from <span className="text-foreground font-medium">two independent perspectives</span>: structured data analysis (Agent 1) + visual pattern recognition (Agent 2), reducing false signals.
              </li>
              <li>
                Each agent has a <span className="text-foreground font-medium">single, focused role</span> — market context, visual pattern, or execution — keeping prompts tight and outputs reliable.
              </li>
            </ul>
          </div>
        </TabsContent>

        {/* ── Tab 2: Position Maintenance ──────────────────────────────────────── */}
        <TabsContent value="maintenance" className="space-y-5 pt-4">
          <div className="rounded-lg border bg-card/50 px-4 py-3">
            <p className="text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">Fan-in pipeline.</span>{" "}
              Agents 1a and 1b run <span className="font-medium text-foreground">independently in parallel</span> — they do not share context with each other.
              Both outputs are then passed together to Agent 2 (Decision) as{" "}
              <span className="text-amber-300 font-medium">technical_output</span> and{" "}
              <span className="text-amber-300 font-medium">sentiment_output</span>, which it uses
              to produce a HOLD / CLOSE / MODIFY recommendation.
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
                Technical and Sentiment agents are <span className="text-foreground font-medium">independent specialists</span> — neither biases the other's analysis, so their outputs are genuinely complementary.
              </li>
              <li>
                The Decision agent is a <span className="text-foreground font-medium">neutral aggregator</span>: it synthesises two scores (technical_score + sentiment_score) into one actionable recommendation, reducing the chance of one-dimensional signals.
              </li>
              <li>
                Closing or modifying a live trade requires <span className="text-foreground font-medium">both technical and macro confirmation</span> — this structure enforces that discipline systematically.
              </li>
            </ul>
          </div>
        </TabsContent>

        {/* ── Tab 3: News Pipelines ─────────────────────────────────────────────── */}
        <TabsContent value="news" className="space-y-6 pt-4">

          {/* ── News Impact Gate ── */}
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold">Pipeline A: News Impact Gate</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Lightweight pre-execution gate. Called before the Market Analysis pipeline is triggered.
                Its output (<span className="text-amber-300 font-medium">signal + reasoning</span>) is
                formatted into a{" "}
                <code className="rounded bg-muted px-1 text-xs">news_context</code> string and passed
                as an optional input into{" "}
                <span className="font-medium text-foreground">Agent 1 (Market Analysis)</span>.
                If no high-impact events are found, the gate returns HOLD and Market Analysis runs
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
                This is the <span className="text-foreground font-medium">only cross-pipeline context link</span>. The News Gate's output is the bridge between the News and Market Analysis pipelines. It gives Agent 1 macro awareness without adding complexity to the main pipeline — Agent 1 simply includes or skips the news section based on whether the string is present.
              </p>
            </div>
          </div>

          <div className="border-t border-border" />

          {/* ── Economic Event Analysis ── */}
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold">Pipeline B: Economic Event Analysis (ForexFactory)</h3>
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
        </TabsContent>
      </Tabs>

      {/* System-wide context map */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <h2 className="text-sm font-semibold">System-wide Context Flow Summary</h2>
        <div className="grid grid-cols-1 gap-2 text-xs md:grid-cols-2 lg:grid-cols-3">
          {[
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
          ].map((item, i) => (
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
    </div>
  );
}
