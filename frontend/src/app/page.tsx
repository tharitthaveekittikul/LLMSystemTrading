"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
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
  const [equityHours, setEquityHours] = useState(24);
  const [autoTradeEnabled, setAutoTradeEnabled] = useState(true);
  const [syncingOrders, setSyncingOrders] = useState(false);

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
          accountsApi.getEquityHistory(activeAccountId, equityHours),
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
  }, [activeAccountId, equityHours]);

  const handleEquityUpdate = useCallback((point: EquityPoint) => {
    setEquityData((prev) => {
      const seen = new Set(prev.map((p) => p.ts));
      if (seen.has(point.ts)) return prev;
      const next = [...prev.slice(-299), point];
      next.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
      return next;
    });
  }, []);

  const handleSyncOrders = useCallback(async () => {
    if (!activeAccountId) return;
    setSyncingOrders(true);
    try {
      const result = await accountsApi.sync(activeAccountId);
      const changed =
        result.positions_closed +
        result.orders_expired +
        result.orders_cancelled +
        result.newly_imported +
        result.updated;
      if (changed === 0) {
        toast.success("Sync complete — everything up to date");
      } else {
        const parts: string[] = [];
        if (result.positions_closed > 0) parts.push(`${result.positions_closed} closed`);
        if (result.orders_expired > 0) parts.push(`${result.orders_expired} expired`);
        if (result.orders_cancelled > 0) parts.push(`${result.orders_cancelled} cancelled`);
        if (result.newly_imported > 0) parts.push(`${result.newly_imported} imported`);
        if (result.updated > 0) parts.push(`${result.updated} updated`);
        toast.success(`Sync complete — ${parts.join(", ")}`);
      }
    } catch {
      toast.error("Failed to sync orders");
    } finally {
      setSyncingOrders(false);
    }
  }, [activeAccountId]);

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
        <div className="flex justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={!activeAccountId || syncingOrders}
            onClick={handleSyncOrders}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${syncingOrders ? "animate-spin" : ""}`} />
            Sync Orders
          </Button>
        </div>
        <KpiBar
          stats={stats}
          statsLoading={statsLoading}
          autoTradeEnabled={autoTradeEnabled}
          onAutoTradeToggle={handleAutoTradeToggle}
        />
        <EquityChart
          data={equityData}
          loading={equityLoading}
          hours={equityHours}
          onHoursChange={setEquityHours}
        />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
          <LivePositions />
          <RecentTrades accountId={activeAccountId} />
        </div>
      </div>
    </SidebarInset>
  );
}
