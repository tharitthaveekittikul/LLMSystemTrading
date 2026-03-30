import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowDown, BookOpen, Database, RefreshCw } from "lucide-react";
import { ResearchLoopProgress } from "@/components/agent-workflow/research-loop-progress";

// ── Reusable service card (not an LLM agent — so a distinct visual style) ────

function ServiceCard({
  icon: Icon,
  title,
  subtitle,
  trigger,
  triggerColor,
  reads,
  produces,
}: {
  icon: React.ElementType;
  title: string;
  subtitle: string;
  trigger: string;
  triggerColor: "teal" | "violet" | "orange";
  reads: string[];
  produces: string[];
}) {
  const styles = {
    teal: {
      border: "border-teal-500/40",
      bg: "bg-teal-500/5",
      title: "text-teal-300",
      icon: "text-teal-400",
      badge: "bg-teal-500/10 border-teal-500/30 text-teal-300",
    },
    violet: {
      border: "border-violet-500/40",
      bg: "bg-violet-500/5",
      title: "text-violet-300",
      icon: "text-violet-400",
      badge: "bg-violet-500/10 border-violet-500/30 text-violet-300",
    },
    orange: {
      border: "border-orange-500/40",
      bg: "bg-orange-500/5",
      title: "text-orange-300",
      icon: "text-orange-400",
      badge: "bg-orange-500/10 border-orange-500/30 text-orange-300",
    },
  }[triggerColor];

  return (
    <Card className={`border-2 ${styles.border} ${styles.bg} w-[340px] shrink-0`}>
      <CardHeader className="pb-2 pt-3">
        <div className="flex items-center gap-2">
          <Icon className={`h-4 w-4 ${styles.icon}`} />
          <CardTitle className={`text-sm ${styles.title}`}>{title}</CardTitle>
        </div>
        <p className="text-[11px] text-muted-foreground ml-6">{subtitle}</p>
        <Badge className={`ml-6 mt-1 w-fit text-[10px] ${styles.badge}`}>{trigger}</Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Reads
          </p>
          <div className="space-y-1">
            {reads.map((f, i) => (
              <div
                key={i}
                className="flex items-start gap-1.5 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-1"
              >
                <span className="mt-0.5 text-blue-400 text-xs">·</span>
                <span className="text-xs text-blue-300">{f}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Produces
          </p>
          <div className="space-y-1">
            {produces.map((f, i) => (
              <div
                key={i}
                className="flex items-start gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1"
              >
                <span className="mt-0.5 text-emerald-400 text-xs">→</span>
                <span className="text-xs text-emerald-300">{f}</span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Step arrow between services ───────────────────────────────────────────────

function StepArrow({ label, color }: { label: string; color: "slate" | "violet" | "orange" }) {
  const badge =
    color === "violet"
      ? "bg-violet-500/20 border-violet-500/40 text-violet-300"
      : color === "orange"
      ? "bg-orange-500/20 border-orange-500/40 text-orange-300"
      : "bg-slate-500/20 border-slate-500/40 text-slate-300";
  const arrow =
    color === "violet"
      ? "text-violet-400"
      : color === "orange"
      ? "text-orange-400"
      : "text-slate-400";

  return (
    <div className="flex flex-col items-center gap-1 py-2">
      <Badge className={`text-[10px] border ${badge}`}>{label}</Badge>
      <ArrowDown className={`h-5 w-5 ${arrow}`} />
    </div>
  );
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export function TabLearning() {
  return (
    <div className="space-y-5 pt-4">
      {/* Live progress tracker */}
      <ResearchLoopProgress />

      {/* Description */}
      <div className="rounded-lg border bg-card/50 px-4 py-3">
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">Self-improving feedback cycle.</span>{" "}
          Every closed trade triggers a lightweight post-trade LLM analysis. Every 30 trades, a
          research loop synthesises 90-day stats into lessons and blocked symbols. Before every
          market analysis call, a{" "}
          <span className="font-medium text-foreground">RAG context block</span> (pure SQL — no
          extra LLM call) is built from the DB and injected into the pipeline, giving the LLM
          visibility into its own historical performance.
        </p>
      </div>

      {/* Cycle diagram */}
      <div className="flex flex-col items-center">
        <ServiceCard
          icon={BookOpen}
          title="1. Post-Trade Analyzer"
          subtitle="LLM call — lightweight, per-trade"
          trigger="fires once per closed trade"
          triggerColor="teal"
          reads={[
            "trade details (symbol, direction, entry, P&L, duration)",
            "AI journal entry (signal, confidence, rationale)",
            "indicators snapshot at entry time",
          ]}
          produces={[
            "correct_signals[] → trades.trade_analysis (DB)",
            "wrong_signals[] → trades.trade_analysis (DB)",
            "key_factor (one sentence) → DB",
            "lesson (one sentence) → DB",
            "confidence_justified (bool) → DB",
          ]}
        />

        <StepArrow label="accumulates in DB…" color="slate" />

        <ServiceCard
          icon={RefreshCw}
          title="2. Research Loop"
          subtitle="LLM call — periodic, strategy-level review"
          trigger="every 30 closed trades"
          triggerColor="violet"
          reads={[
            "90-day overall stats (total trades, WR, P&L)",
            "per-symbol win rates & P&L",
            "signal reliability from trade_analysis (correct vs wrong)",
            "high-confidence WR calibration",
            "recent loss lessons (up to 10)",
          ]}
          produces={[
            "lessons[] → research_config.json",
            "blocked_symbols[] (WR < 40%, n ≥ 20) → research_config.json",
            "suggested_params{} (confidence threshold etc.) → research_config.json",
            "stats_snapshot{} → research_config.json",
          ]}
        />

        <StepArrow label="DB + research_config.json →" color="orange" />

        <ServiceCard
          icon={Database}
          title="3. RAG Context Builder"
          subtitle="No LLM — pure SQL aggregation"
          trigger="before every market analysis & maintenance call"
          triggerColor="orange"
          reads={[
            "DB: closed trades (last 90 days)",
            "DB: ai_journal (confidence, timeframe, indicators)",
            "research_config.json (lessons, blocked_symbols)",
          ]}
          produces={[
            "[1] Overall Performance — WR, P&L, avg win/loss",
            "[2] Last 20 Closed Trades — outcomes + lessons",
            "[3] Signal Reliability — correct vs wrong % per indicator",
            "[4] Symbol Performance — per-symbol WR & P&L",
            "[5] Timeframe Performance",
            "[6] Confidence Calibration — overconfidence flag",
            "[7] Session Patterns — London / NY / Tokyo WR",
            "[8] Lessons from Recent Losses + auto-generated lessons",
          ]}
        />

        {/* Injection note */}
        <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-300 text-center max-w-[340px]">
          ⇢{" "}
          <span className="font-semibold">rag_context</span> injected as input into{" "}
          <span className="font-medium">Market Analysis Agent 1</span>,{" "}
          <span className="font-medium">Maintenance Agent 1a</span>, and{" "}
          <span className="font-medium">1b</span>
        </div>
      </div>

      {/* Insight */}
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
        <p className="text-sm font-semibold text-emerald-300 mb-1">
          Why this feedback cycle matters
        </p>
        <ul className="text-xs text-muted-foreground space-y-1 list-disc list-inside">
          <li>
            The LLM sees its own{" "}
            <span className="text-foreground font-medium">historical accuracy</span> on every call
            — enabling self-calibration of confidence scores over time.
          </li>
          <li>
            <span className="text-foreground font-medium">Signal reliability</span> is computed
            from real trade outcomes — so misleading indicators get flagged automatically.
          </li>
          <li>
            <span className="text-foreground font-medium">Blocked symbols</span> (WR &lt; 40%
            over 20+ trades) are injected as context, preventing repeat documented losses.
          </li>
          <li>
            The Research Loop is{" "}
            <span className="text-foreground font-medium">
              rate-limited to every 30 trades
            </span>{" "}
            — adapting to regime changes without over-fitting to short-term noise.
          </li>
          <li>
            The RAG Context Builder adds{" "}
            <span className="text-foreground font-medium">zero LLM cost</span> — it is pure SQL
            aggregation, so every call gets richer context with no extra API spend.
          </li>
        </ul>
      </div>
    </div>
  );
}
