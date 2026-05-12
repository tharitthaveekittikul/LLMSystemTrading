"use client";
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { llmAnalyticsApi } from "@/lib/api";
import type {
  ConfidenceBucket,
  LearningLesson,
  ResearchConfig,
  SignalReliabilityRow,
} from "@/types/trading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ResearchLoopProgress } from "../agent-workflow/research-loop-progress";

// ── Confidence Calibration ────────────────────────────────────────────────────

function ConfidenceCalibrationCard({ days }: { days: number }) {
  const [data, setData] = useState<ConfidenceBucket[]>([]);

  useEffect(() => {
    llmAnalyticsApi
      .getConfidenceCalibration(days)
      .then(setData)
      .catch(() => setData([]));
  }, [days]);

  if (data.length === 0)
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Confidence Calibration</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            No calibration data yet — need closed trades with journal entries.
          </p>
        </CardContent>
      </Card>
    );

  const maxWr = Math.max(...data.map((d) => d.win_rate), 0.01);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Confidence Calibration</CardTitle>
        <p className="text-xs text-muted-foreground">
          Actual win rate vs stated LLM confidence
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {data.map((b) => (
          <div key={b.bucket} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">
                {b.bucket.replace("_", " ")} ({b.label})
                {b.overconfident && (
                  <Badge
                    variant="destructive"
                    className="ml-2 text-[10px] px-1 py-0"
                  >
                    overconfident
                  </Badge>
                )}
              </span>
              <span className="tabular-nums">
                {(b.win_rate * 100).toFixed(1)}% WR
                <span className="text-muted-foreground ml-1">
                  ({b.trade_count})
                </span>
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${b.overconfident ? "bg-destructive" : b.win_rate >= 0.55 ? "bg-green-500" : "bg-amber-500"}`}
                style={{ width: `${(b.win_rate / maxWr) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ── Signal Reliability ────────────────────────────────────────────────────────

function SignalReliabilityCard({ days }: { days: number }) {
  const [data, setData] = useState<SignalReliabilityRow[]>([]);

  useEffect(() => {
    llmAnalyticsApi
      .getSignalReliability(days)
      .then(setData)
      .catch(() => setData([]));
  }, [days]);

  if (data.length === 0)
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Signal Reliability</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            No signal data yet — need post-trade analysis records.
          </p>
        </CardContent>
      </Card>
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Signal Reliability</CardTitle>
        <p className="text-xs text-muted-foreground">
          Which indicators actually predicted the right direction
        </p>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground border-b">
              <th className="text-left py-1 font-medium">Signal</th>
              <th className="text-right py-1 font-medium">Reliable %</th>
              <th className="text-right py-1 font-medium">Samples</th>
              <th className="text-right py-1 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr
                key={row.signal}
                className="border-b border-border/40 last:border-0"
              >
                <td className="py-1.5 font-mono">{row.signal}</td>
                <td
                  className={`py-1.5 text-right tabular-nums ${row.is_reliable ? "text-green-500" : "text-red-500"}`}
                >
                  {row.reliable_pct.toFixed(1)}%
                </td>
                <td className="py-1.5 text-right text-muted-foreground tabular-nums">
                  {row.sample_count}
                </td>
                <td className="py-1.5 text-right">
                  <Badge
                    variant={row.is_reliable ? "outline" : "destructive"}
                    className="text-[10px] px-1 py-0"
                  >
                    {row.is_reliable ? "✅ reliable" : "❌ weak"}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// ── Lessons ───────────────────────────────────────────────────────────────────

function LessonsCard() {
  const [data, setData] = useState<LearningLesson[]>([]);

  useEffect(() => {
    llmAnalyticsApi
      .getLessons(15)
      .then(setData)
      .catch(() => setData([]));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Lessons from Recent Losses</CardTitle>
        <p className="text-xs text-muted-foreground">
          Extracted by post-trade AI analysis
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No lessons yet — needs closed losing trades with post-trade
            analysis.
          </p>
        )}
        {data.map((l, i) => (
          <div
            key={i}
            className="rounded-md border border-border/50 p-2 space-y-1"
          >
            <p className="text-xs">{l.lesson}</p>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <span className="font-mono">{l.symbol}</span>
              <span>{l.direction}</span>
              <span className="text-red-500 tabular-nums">
                {l.profit.toFixed(2)}
              </span>
              <span className="ml-auto">
                {l.closed_at ? new Date(l.closed_at).toLocaleDateString() : ""}
              </span>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ── Research Config ───────────────────────────────────────────────────────────

function ResearchConfigCard() {
  const [cfg, setCfg] = useState<ResearchConfig | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const fetchConfig = () => {
    llmAnalyticsApi
      .getResearchConfig()
      .then(setCfg)
      .catch(() => setCfg(null));
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Research Loop</CardTitle>
        <ResearchLoopProgress onComplete={fetchConfig} />
        <p className="text-xs text-muted-foreground">
          Auto-runs every 30 closed trades.
          {cfg?.last_run_at && (
            <>
              {" "}
              Last run:{" "}
              <span className="font-mono">
                {new Date(cfg.last_run_at).toLocaleString()}
              </span>
            </>
          )}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {!cfg ||
        (cfg.lessons.length === 0 && cfg.blocked_symbols.length === 0) ? (
          <p className="text-xs text-muted-foreground">
            Not yet run — needs 30 closed trades.
          </p>
        ) : (
          <>
            {cfg.blocked_symbols.length > 0 && (
              <div>
                <p className="text-xs font-medium mb-1 text-destructive">
                  Blocked Symbols (WR &lt; 40%)
                </p>
                <div className="flex flex-wrap gap-1">
                  {cfg.blocked_symbols.map((s) => (
                    <Badge
                      key={s}
                      variant="destructive"
                      className="text-[10px]"
                    >
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {cfg.lessons.length > 0 && (
              <div>
                <p className="text-xs font-medium mb-1">
                  Auto-Generated Lessons
                </p>
                <ul className="space-y-1">
                  {cfg.lessons.map((l, i) => (
                    <li
                      key={i}
                      className="text-xs text-muted-foreground flex gap-2"
                    >
                      <span className="text-primary">•</span>
                      <span>{l}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {cfg.lesson_history && cfg.lesson_history.length > 0 && (
              <div>
                <button
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setHistoryOpen((v) => !v)}
                >
                  {historyOpen ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )}
                  Lesson History ({cfg.lesson_history.length} total)
                </button>
                {historyOpen && (
                  <ul className="mt-2 space-y-1.5">
                    {[...cfg.lesson_history].reverse().map((entry, i) => (
                      <li key={i} className="rounded-md border border-border/40 p-2 space-y-0.5">
                        <p className="text-xs text-muted-foreground">{entry.lesson}</p>
                        <p className="text-[10px] text-muted-foreground/60 font-mono">
                          {new Date(entry.recorded_at).toLocaleString()}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {cfg.suggested_params &&
              Object.keys(cfg.suggested_params).length > 0 && (
                <div>
                  <p className="text-xs font-medium mb-1">
                    Suggested Parameters
                  </p>
                  <pre className="text-[10px] bg-muted rounded p-2 overflow-x-auto">
                    {JSON.stringify(cfg.suggested_params, null, 2)}
                  </pre>
                </div>
              )}
            {cfg.stats_snapshot &&
              Object.keys(cfg.stats_snapshot).length > 0 && (
                <div className="flex gap-4 text-xs text-muted-foreground">
                  <span>
                    Trades:{" "}
                    <span className="text-foreground font-mono">
                      {String(cfg.stats_snapshot.total_trades ?? "—")}
                    </span>
                  </span>
                  <span>
                    WR:{" "}
                    <span className="text-foreground font-mono">
                      {cfg.stats_snapshot.win_rate != null
                        ? `${(Number(cfg.stats_snapshot.win_rate) * 100).toFixed(1)}%`
                        : "—"}
                    </span>
                  </span>
                  <span>
                    P&L:{" "}
                    <span className="text-foreground font-mono">
                      {cfg.stats_snapshot.pnl != null
                        ? Number(cfg.stats_snapshot.pnl).toFixed(2)
                        : "—"}
                    </span>
                  </span>
                </div>
              )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function LearningTab({ days }: { days: number }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <ConfidenceCalibrationCard days={days} />
      <SignalReliabilityCard days={days} />
      <LessonsCard />
      <ResearchConfigCard />
    </div>
  );
}
