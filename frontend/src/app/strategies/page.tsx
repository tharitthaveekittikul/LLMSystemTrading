"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { strategiesApi } from "@/lib/api/strategies";
import type { Strategy, StrategyStats } from "@/types/trading";
import { Plus, Edit2, Trash2 } from "lucide-react";

const TYPE_COLORS: Record<string, string> = {
  config: "bg-blue-100 text-blue-800",
  prompt: "bg-purple-100 text-purple-800",
  code: "bg-green-100 text-green-800",
  llm_only: "bg-purple-100 text-purple-800",
  rule_then_llm: "bg-blue-100 text-blue-800",
  rule_only: "bg-green-100 text-green-800",
  hybrid_validator: "bg-amber-100 text-amber-800",
  multi_agent: "bg-orange-100 text-orange-800",
};

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [statsMap, setStatsMap] = useState<Record<number, StrategyStats>>({});

  useEffect(() => {
    (async () => {
      try {
        const data = await strategiesApi.list();
        setStrategies(data);
        // Fetch stats for all strategies in parallel
        const statsEntries = await Promise.allSettled(
          data.map(s => strategiesApi.getStats(s.id).then(stats => [s.id, stats] as const))
        );
        const map: Record<number, StrategyStats> = {};
        for (const entry of statsEntries) {
          if (entry.status === "fulfilled") {
            const [id, stats] = entry.value;
            map[id] = stats;
          }
        }
        setStatsMap(map);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function handleToggle(strategy: Strategy) {
    try {
      const updated = await strategiesApi.update(strategy.id, {
        is_active: !strategy.is_active,
      });
      setStrategies((prev) =>
        prev.map((s) => (s.id === strategy.id ? updated : s)),
      );
    } catch (err) {
      console.error(err);
    }
  }

  async function handleDelete(id: number) {
    try {
      await strategiesApi.delete(id);
      setStrategies((prev) => prev.filter((s) => s.id !== id));
      setDeletingId(null);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <SidebarInset>
      <AppHeader title="Strategies" showAccountSelector={false} showConnectionStatus={false} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Trading Strategies</h2>
            <p className="text-sm text-muted-foreground">
              Manage automated trading strategies and account bindings
            </p>
          </div>
          <Button asChild>
            <Link href="/strategies/new">
              <Plus className="mr-2 h-4 w-4" />
              New Strategy
            </Link>
          </Button>
        </div>

        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="h-40 animate-pulse bg-muted rounded-lg" />
              </Card>
            ))}
          </div>
        ) : strategies.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center">
            <p className="text-muted-foreground">No strategies yet</p>
            <Button asChild variant="link" className="mt-2">
              <Link href="/strategies/new">Create your first strategy</Link>
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {strategies.map((s) => (
              <Card key={s.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-base">{s.name}</CardTitle>
                    <Switch
                      checked={s.is_active}
                      onCheckedChange={() => handleToggle(s)}
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
                      className={TYPE_COLORS[s.execution_mode] ?? TYPE_COLORS[s.strategy_type]}
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
                  <div className="text-xs text-muted-foreground">
                    {s.symbols.join(", ")} · {s.binding_count} account
                    {s.binding_count !== 1 ? "s" : ""} bound
                  </div>
                  {/* Performance stats */}
                  {statsMap[s.id] && (
                    <div className="border-t pt-2 mt-1 space-y-1.5">
                      {statsMap[s.id].backtest && (
                        <div>
                          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">
                            Latest Backtest · {statsMap[s.id].backtest!.symbol} {statsMap[s.id].backtest!.timeframe}
                          </p>
                          <div className="flex gap-3 text-xs">
                            <span>
                              WR{" "}
                              <span className="font-semibold">
                                {statsMap[s.id].backtest!.win_rate != null
                                  ? `${(statsMap[s.id].backtest!.win_rate! * 100).toFixed(1)}%`
                                  : "—"}
                              </span>
                            </span>
                            <span>
                              PF{" "}
                              <span className="font-semibold">
                                {statsMap[s.id].backtest!.profit_factor?.toFixed(2) ?? "—"}
                              </span>
                            </span>
                            <span>
                              Ret{" "}
                              <span className={`font-semibold ${(statsMap[s.id].backtest!.total_return_pct ?? 0) >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {statsMap[s.id].backtest!.total_return_pct != null
                                  ? `${statsMap[s.id].backtest!.total_return_pct! >= 0 ? "+" : ""}${statsMap[s.id].backtest!.total_return_pct!.toFixed(1)}%`
                                  : "—"}
                              </span>
                            </span>
                          </div>
                        </div>
                      )}
                      {!statsMap[s.id].backtest && (
                        <p className="text-[10px] text-muted-foreground">No backtest run yet</p>
                      )}
                      {statsMap[s.id].live && (
                        <div>
                          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Live</p>
                          <div className="flex gap-3 text-xs">
                            <span>
                              Trades{" "}
                              <span className="font-semibold">{statsMap[s.id].live!.total_trades}</span>
                            </span>
                            <span>
                              WR{" "}
                              <span className="font-semibold">
                                {(statsMap[s.id].live!.win_rate * 100).toFixed(1)}%
                              </span>
                            </span>
                            <span>
                              P&L{" "}
                              <span className={`font-semibold ${statsMap[s.id].live!.total_pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {statsMap[s.id].live!.total_pnl >= 0 ? "+" : ""}
                                {statsMap[s.id].live!.total_pnl.toFixed(2)}
                              </span>
                            </span>
                          </div>
                        </div>
                      )}
                      {!statsMap[s.id].live && (
                        <p className="text-[10px] text-muted-foreground">No live trades</p>
                      )}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" asChild>
                      <Link href={`/strategies/${s.id}/edit`}>
                        <Edit2 className="mr-1 h-3 w-3" />
                        Edit
                      </Link>
                    </Button>
                    <Dialog
                      open={deletingId === s.id}
                      onOpenChange={(open) => setDeletingId(open ? s.id : null)}
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
                            onClick={() => setDeletingId(null)}
                          >
                            Cancel
                          </Button>
                          <Button
                            variant="destructive"
                            onClick={() => handleDelete(s.id)}
                          >
                            Delete
                          </Button>
                        </DialogFooter>
                      </DialogContent>
                    </Dialog>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </SidebarInset>
  );
}
