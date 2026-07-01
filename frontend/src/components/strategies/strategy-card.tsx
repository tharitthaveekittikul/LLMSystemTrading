import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Edit2, Trash2, Play, Loader2 } from "lucide-react";
import type { Strategy, StrategyBinding, StrategyStats } from "@/types/trading";

export const TYPE_COLORS: Record<string, string> = {
  config: "bg-blue-100 text-blue-800",
  prompt: "bg-purple-100 text-purple-800",
  code: "bg-green-100 text-green-800",
  llm_only: "bg-purple-100 text-purple-800",
  rule_then_llm: "bg-blue-100 text-blue-800",
  rule_only: "bg-green-100 text-green-800",
  hybrid_validator: "bg-amber-100 text-amber-800",
  multi_agent: "bg-orange-100 text-orange-800",
};

interface StrategyCardProps {
  strategy: Strategy;
  stats: StrategyStats | undefined;
  bindings: StrategyBinding[] | undefined;
  deletingId: number | null;
  triggeringId: number | null;
  onToggle: (strategy: Strategy) => void;
  onTrigger: (id: number) => void;
  onDelete: (id: number) => void;
  onDeleteDialogChange: (id: number | null) => void;
}

export function StrategyCard({
  strategy: s,
  stats,
  bindings,
  deletingId,
  triggeringId,
  onToggle,
  onTrigger,
  onDelete,
  onDeleteDialogChange,
}: StrategyCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base">{s.name}</CardTitle>
          <Switch
            checked={s.is_active}
            onCheckedChange={() => onToggle(s)}
          />
        </div>
        {s.description && (
          <p className="text-xs text-muted-foreground">
            {s.description}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1">
          <Badge
            variant="secondary"
            className={
              TYPE_COLORS[s.execution_mode] ??
              TYPE_COLORS[s.strategy_type]
            }
          >
            {s.execution_mode.replace(/_/g, " ")}
          </Badge>
          <Badge variant="outline">{s.timeframe}</Badge>
          <Badge variant="outline">
            {s.trigger_type === "candle_close"
              ? "Candle close"
              : `Every ${s.interval_minutes}m`}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground space-y-0.5">
          <div>{s.symbols.join(", ")}</div>
          {bindings && bindings.length > 0 ? (
            <div className="flex flex-col gap-1 mt-0.5">
              {bindings.map((b) => (
                <div key={b.id} className="flex items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className={
                      b.is_live
                        ? "border-green-500 text-green-700"
                        : ""
                    }
                  >
                    {b.is_live ? "Real" : "Demo"}
                  </Badge>
                  <span>
                    [{b.login}] {b.account_name}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <span>No accounts bound</span>
          )}
        </div>
        {/* Performance stats */}
        {stats && (
          <div className="border-t pt-2 mt-1 space-y-1.5">
            {stats.backtest && (
              <div>
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">
                  Latest Backtest · {stats.backtest.symbol}{" "}
                  {stats.backtest.timeframe}
                </p>
                <div className="flex gap-3 text-xs">
                  <span>
                    WR{" "}
                    <span className="font-semibold">
                      {stats.backtest.win_rate != null
                        ? `${(stats.backtest.win_rate * 100).toFixed(1)}%`
                        : "—"}
                    </span>
                  </span>
                  <span>
                    PF{" "}
                    <span className="font-semibold">
                      {stats.backtest.profit_factor?.toFixed(2) ?? "—"}
                    </span>
                  </span>
                  <span>
                    Ret{" "}
                    <span
                      className={`font-semibold ${(stats.backtest.total_return_pct ?? 0) >= 0 ? "text-green-600" : "text-red-500"}`}
                    >
                      {stats.backtest.total_return_pct != null
                        ? `${stats.backtest.total_return_pct >= 0 ? "+" : ""}${stats.backtest.total_return_pct.toFixed(1)}%`
                        : "—"}
                    </span>
                  </span>
                </div>
              </div>
            )}
            {!stats.backtest && (
              <p className="text-[10px] text-muted-foreground">
                No backtest run yet
              </p>
            )}
            {stats.live && (
              <div>
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">
                  Live
                </p>
                <div className="flex gap-3 text-xs">
                  <span>
                    Trades{" "}
                    <span className="font-semibold">
                      {stats.live.total_trades}
                    </span>
                  </span>
                  <span>
                    WR{" "}
                    <span className="font-semibold">
                      {(stats.live.win_rate * 100).toFixed(1)}
                      %
                    </span>
                  </span>
                  <span>
                    P&L{" "}
                    <span
                      className={`font-semibold ${stats.live.total_pnl >= 0 ? "text-green-600" : "text-red-500"}`}
                    >
                      {stats.live.total_pnl >= 0 ? "+" : ""}
                      {stats.live.total_pnl.toFixed(2)}
                    </span>
                  </span>
                </div>
              </div>
            )}
            {!stats.live && (
              <p className="text-[10px] text-muted-foreground">
                No live trades
              </p>
            )}
          </div>
        )}
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onTrigger(s.id)}
            disabled={!s.is_active || triggeringId === s.id}
          >
            {triggeringId === s.id ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <Play className="mr-1 h-3 w-3" />
            )}
            Trigger
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href={`/strategies/${s.id}/edit`}>
              <Edit2 className="mr-1 h-3 w-3" />
              Edit
            </Link>
          </Button>
          <Dialog
            open={deletingId === s.id}
            onOpenChange={(open) =>
              onDeleteDialogChange(open ? s.id : null)
            }
          >
            <DialogTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="text-destructive hover:text-destructive"
              >
                <Trash2 className="mr-1 h-3 w-3" />
                Delete
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete strategy?</DialogTitle>
                <DialogDescription>
                  This will remove &ldquo;{s.name}&rdquo; and all
                  scheduler jobs. This cannot be undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => onDeleteDialogChange(null)}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => onDelete(s.id)}
                >
                  Delete
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </CardContent>
    </Card>
  );
}
