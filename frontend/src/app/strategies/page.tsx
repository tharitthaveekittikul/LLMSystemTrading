"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { strategiesApi } from "@/lib/api/strategies";
import { accountsApi } from "@/lib/api/accounts";
import type { Strategy, StrategyBinding, StrategyStats, Account } from "@/types/trading";
import { Plus, Edit2, LayoutGrid, List } from "lucide-react";
import { StrategyCard } from "@/components/strategies/strategy-card";

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"strategies" | "accounts">("strategies");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [triggeringId, setTriggeringId] = useState<number | null>(null);
  const [statsMap, setStatsMap] = useState<Record<number, StrategyStats>>({});
  const [bindingsMap, setBindingsMap] = useState<
    Record<number, StrategyBinding[]>
  >({});

  useEffect(() => {
    (async () => {
      try {
        const [stratData, accData] = await Promise.all([
          strategiesApi.list(),
          accountsApi.list(),
        ]);
        setStrategies(stratData);
        setAccounts(accData);
        // Fetch stats and bindings for all strategies in parallel
        const [statsEntries, bindingsEntries] = await Promise.all([
          Promise.allSettled(
            stratData.map((s) =>
              strategiesApi
                .getStats(s.id)
                .then((stats) => [s.id, stats] as const),
            ),
          ),
          Promise.allSettled(
            stratData.map((s) =>
              strategiesApi.bindings(s.id).then((b) => [s.id, b] as const),
            ),
          ),
        ]);
        const map: Record<number, StrategyStats> = {};
        for (const entry of statsEntries) {
          if (entry.status === "fulfilled") {
            const [id, stats] = entry.value;
            map[id] = stats;
          }
        }
        setStatsMap(map);
        const bmap: Record<number, StrategyBinding[]> = {};
        for (const entry of bindingsEntries) {
          if (entry.status === "fulfilled") {
            const [id, bindings] = entry.value;
            bmap[id] = bindings;
          }
        }
        setBindingsMap(bmap);
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

  async function handleTrigger(id: number) {
    try {
      setTriggeringId(id);
      await strategiesApi.trigger(id);
    } catch (err) {
      console.error(err);
    } finally {
      setTriggeringId(null);
    }
  }

  return (
    <SidebarInset>
      <AppHeader
        title="Strategies"
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Trading Strategies</h2>
            <p className="text-sm text-muted-foreground">
              Manage automated trading strategies and account bindings
            </p>
          </div>
          <div className="flex items-center gap-4">
            <Tabs
              value={viewMode}
              onValueChange={(v) => setViewMode(v as "strategies" | "accounts")}
              className="w-auto"
            >
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="strategies" className="flex items-center gap-2">
                  <LayoutGrid className="h-4 w-4" />
                  Strategies
                </TabsTrigger>
                <TabsTrigger value="accounts" className="flex items-center gap-2">
                  <List className="h-4 w-4" />
                  Accounts
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <Button asChild>
              <Link href="/strategies/new">
                <Plus className="mr-2 h-4 w-4" />
                New Strategy
              </Link>
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="h-40 animate-pulse bg-muted rounded-lg" />
              </Card>
            ))}
          </div>
        ) : viewMode === "strategies" ? (
          strategies.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center">
              <p className="text-muted-foreground">No strategies yet</p>
              <Button asChild variant="link" className="mt-2">
                <Link href="/strategies/new">Create your first strategy</Link>
              </Button>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {strategies.map((s) => (
                <StrategyCard
                  key={s.id}
                  strategy={s}
                  stats={statsMap[s.id]}
                  bindings={bindingsMap[s.id]}
                  deletingId={deletingId}
                  triggeringId={triggeringId}
                  onToggle={handleToggle}
                  onTrigger={handleTrigger}
                  onDelete={handleDelete}
                  onDeleteDialogChange={setDeletingId}
                />
              ))}
            </div>
          )
        ) : (
          /* Accounts View */
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {accounts.map((acc) => {
              const boundStrategies = strategies.filter((s) =>
                bindingsMap[s.id]?.some((b) => b.account_id === acc.id),
              );

              return (
                <Card key={acc.id} className="overflow-hidden">
                  <CardHeader className="bg-muted/30 pb-3">
                    <div className="flex items-center justify-between">
                      <div className="space-y-1">
                        <CardTitle className="text-base flex items-center gap-2">
                          {acc.name}
                          <Badge
                            variant="secondary"
                            className={
                              acc.is_live
                                ? "bg-green-100 text-green-700"
                                : "bg-blue-100 text-blue-700"
                            }
                          >
                            {acc.is_live ? "Real" : "Demo"}
                          </Badge>
                        </CardTitle>
                        <p className="text-xs text-muted-foreground">
                          Login:{" "}
                          <span className="font-mono text-foreground">
                            {acc.login}
                          </span>{" "}
                          • {acc.broker}
                        </p>
                      </div>
                      <Switch
                        checked={acc.is_active}
                        disabled // Account active state managed in Accounts page
                      />
                    </div>
                  </CardHeader>
                  <CardContent className="pt-4 space-y-4">
                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                        Bound Strategies
                        <Badge variant="outline" className="text-[10px] h-4">
                          {boundStrategies.length}
                        </Badge>
                      </h4>
                      {boundStrategies.length === 0 ? (
                        <p className="text-xs text-muted-foreground italic py-2">
                          No strategies bound to this account.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {boundStrategies.map((s) => {
                            const binding = bindingsMap[s.id].find(
                              (b) => b.account_id === acc.id,
                            )!;
                            return (
                              <div
                                key={s.id}
                                className="flex items-center justify-between rounded-md border p-2 text-sm"
                              >
                                <div className="flex items-center gap-2">
                                  <div
                                    className={`h-2 w-2 rounded-full ${s.is_active && binding.is_active ? "bg-green-500" : "bg-gray-300"}`}
                                  />
                                  <span className="font-medium">{s.name}</span>
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] px-1 py-0 h-4"
                                  >
                                    {s.timeframe}
                                  </Badge>
                                </div>
                                <div className="flex items-center gap-2">
                                  <Switch
                                    checked={binding.is_active}
                                    onCheckedChange={async () => {
                                      try {
                                        await strategiesApi.toggleBinding(
                                          s.id,
                                          acc.id,
                                          !binding.is_active,
                                        );
                                        // Update local state
                                        setBindingsMap((prev) => ({
                                          ...prev,
                                          [s.id]: prev[s.id].map((b) =>
                                            b.account_id === acc.id
                                              ? {
                                                  ...b,
                                                  is_active: !b.is_active,
                                                }
                                              : b,
                                          ),
                                        }));
                                      } catch (err) {
                                        console.error(err);
                                      }
                                    }}
                                  />
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6"
                                    asChild
                                  >
                                    <Link href={`/strategies/${s.id}/edit`}>
                                      <Edit2 className="h-3 w-3" />
                                    </Link>
                                  </Button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full text-xs h-8"
                      asChild
                    >
                      <Link href={`/accounts`}>Manage Account</Link>
                    </Button>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </SidebarInset>
  );
}
