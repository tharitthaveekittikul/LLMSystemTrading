"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { KillSwitchBanner } from "@/components/dashboard/kill-switch-banner";
import { KpiBar } from "@/components/dashboard/kpi-bar";
import { EquityChart } from "@/components/dashboard/equity-chart";
import { LivePositions } from "@/components/dashboard/live-positions";
import { RecentTrades } from "@/components/dashboard/recent-trades";
import { DashboardProvider } from "@/components/dashboard/dashboard-provider";
import { useTradingStore } from "@/hooks/use-trading-store";
import { accountsApi } from "@/lib/api/accounts";
import type { AccountStats, EquityPoint } from "@/types/trading";

export default function DashboardPage() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);

  const [stats, setStats] = useState<AccountStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [equityData, setEquityData] = useState<EquityPoint[]>([]);
  const [equityLoading, setEquityLoading] = useState(false);
  const [autoTradeEnabled, setAutoTradeEnabled] = useState(true);

  useEffect(() => {
    if (!activeAccountId) {
      setStats(null);
      setEquityData([]);
      return;
    }

    (async () => {
      setStatsLoading(true);
      setEquityLoading(true);
      try {
        const [stats, equity, account] = await Promise.all([
          accountsApi.getStats(activeAccountId),
          accountsApi.getEquityHistory(activeAccountId, 24),
          accountsApi.get(activeAccountId),
        ]);
        setStats(stats);
        setEquityData(equity);
        setAutoTradeEnabled(account.auto_trade_enabled);
      } catch {
        setStats(null);
        setEquityData([]);
      } finally {
        setStatsLoading(false);
        setEquityLoading(false);
      }
    })();
  }, [activeAccountId]);

  const handleEquityUpdate = useCallback((point: EquityPoint) => {
    setEquityData((prev) => {
      const next = [...prev.slice(-199), point];
      next.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
      return next;
    });
  }, []);

  const handleAutoTradeToggle = useCallback(
    async (enabled: boolean) => {
      if (!activeAccountId) return;
      setAutoTradeEnabled(enabled);
      try {
        await accountsApi.update(activeAccountId, {
          auto_trade_enabled: enabled,
        });
      } catch {
        setAutoTradeEnabled(!enabled);
      }
    },
    [activeAccountId],
  );

  return (
    <SidebarInset>
      <AppHeader title="Dashboard" />
      <DashboardProvider onEquityUpdate={handleEquityUpdate} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <KillSwitchBanner />
        <KpiBar
          stats={stats}
          statsLoading={statsLoading}
          autoTradeEnabled={autoTradeEnabled}
          onAutoTradeToggle={handleAutoTradeToggle}
        />
        <EquityChart data={equityData} loading={equityLoading} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
          <LivePositions />
          <RecentTrades accountId={activeAccountId} />
        </div>
      </div>
    </SidebarInset>
  );
}
