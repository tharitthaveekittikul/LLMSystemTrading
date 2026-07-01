import { BrainCircuit } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TableCell, TableRow } from "@/components/ui/table";
import type { Trade, TradeAnalysis } from "@/types/trading";
import { cn } from "@/lib/utils";

// ── Scorecard ─────────────────────────────────────────────────────────────────

export function Scorecard({ trades }: { trades: Trade[] }) {
  const closed = trades.filter((t) => t.closed_at !== null);
  const wins = closed.filter((t) => (t.profit ?? 0) > 0);
  const totalPnl = closed.reduce((s, t) => s + (t.profit ?? 0), 0);
  const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;

  const stats = [
    { label: "Total Trades", value: trades.length },
    { label: "Closed", value: closed.length },
    {
      label: "Win Rate",
      value: `${winRate.toFixed(1)}%`,
      color:
        winRate >= 50
          ? "text-green-600 dark:text-green-400"
          : "text-red-600 dark:text-red-400",
    },
    {
      label: "Total P&L",
      value: (totalPnl >= 0 ? "+" : "") + totalPnl.toFixed(2),
      color:
        totalPnl > 0
          ? "text-green-600 dark:text-green-400"
          : totalPnl < 0
            ? "text-red-600 dark:text-red-400"
            : "",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((s) => (
        <Card key={s.label} className="border-l-2 border-l-primary shadow-sm">
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">{s.label}</p>
            <p className={`text-lg font-semibold font-mono ${s.color ?? ""}`}>
              {s.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Post-trade analysis panel ─────────────────────────────────────────────────

export function TradeAnalysisPanel({
  trade,
  onAnalyze,
  analyzing,
}: {
  trade: Trade;
  onAnalyze: (id: number) => void;
  analyzing: boolean;
}) {
  const parsed: TradeAnalysis | null = (() => {
    if (!trade.trade_analysis) return null;
    try { return JSON.parse(trade.trade_analysis); } catch { return null; }
  })();

  return (
    <div className="px-4 py-3 bg-muted/40 border-t space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <BrainCircuit className="h-3.5 w-3.5" />
          AI Post-Trade Analysis
        </div>
        {trade.closed_at && (
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs px-2"
            onClick={() => onAnalyze(trade.id)}
            disabled={analyzing}
          >
            {analyzing ? "Running…" : parsed ? "Re-analyze" : "Run Analysis"}
          </Button>
        )}
      </div>

      {parsed ? (
        <div className="grid gap-2 sm:grid-cols-2 text-xs">
          <div className="space-y-1">
            <p className="font-medium text-foreground">Key Factor</p>
            <p className="text-muted-foreground">{parsed.key_factor}</p>
          </div>
          <div className="space-y-1">
            <p className="font-medium text-foreground">Lesson</p>
            <p className="text-muted-foreground">{parsed.lesson}</p>
          </div>
          <div className="space-y-1">
            <p className="font-medium text-foreground">Correct Signals</p>
            <div className="flex flex-wrap gap-1">
              {parsed.correct_signals.length > 0
                ? parsed.correct_signals.map((s) => (
                    <Badge key={s} className="text-xs bg-green-500/15 text-green-700 dark:text-green-400 border-0">{s}</Badge>
                  ))
                : <span className="text-muted-foreground italic">none</span>}
            </div>
          </div>
          <div className="space-y-1">
            <p className="font-medium text-foreground">Wrong Signals</p>
            <div className="flex flex-wrap gap-1">
              {parsed.wrong_signals.length > 0
                ? parsed.wrong_signals.map((s) => (
                    <Badge key={s} className="text-xs bg-red-500/15 text-red-700 dark:text-red-400 border-0">{s}</Badge>
                  ))
                : <span className="text-muted-foreground italic">none</span>}
            </div>
          </div>
          <div className="space-y-1 sm:col-span-2">
            <span className="font-medium text-foreground">Confidence Justified: </span>
            <Badge className={cn("text-xs border-0", parsed.confidence_justified ? "bg-green-500/15 text-green-700 dark:text-green-400" : "bg-orange-500/15 text-orange-700 dark:text-orange-400")}>
              {parsed.confidence_justified ? "Yes" : "No"}
            </Badge>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic">
          {trade.closed_at
            ? "No analysis yet — click \"Run Analysis\" to generate one."
            : "Trade is still open."}
        </p>
      )}
    </div>
  );
}

// ── Skeleton rows ─────────────────────────────────────────────────────────────

export function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 10 }).map((_, j) => (
            <TableCell key={j}>
              <div className="h-4 rounded bg-muted animate-pulse w-16" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

// ── Loading fallback (Suspense) ─────────────────────────────────────────────

export function LoadingFallback() {
  return (
    <SidebarInset>
      <AppHeader title="Trades" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    </SidebarInset>
  );
}
