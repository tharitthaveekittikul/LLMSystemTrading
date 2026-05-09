"use client";

import { useTradingStore } from "@/hooks/use-trading-store";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import type { AccountStats } from "@/types/trading";

interface KpiBarProps {
  stats: AccountStats | null;
  statsLoading: boolean;
  autoTradeEnabled: boolean;
  onAutoTradeToggle: (enabled: boolean) => void;
}

function KpiCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="card-surface p-4 flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold text-muted-foreground/50 uppercase tracking-widest">
        {label}
      </span>
      <span className={cn("text-xl font-bold tabular-nums tracking-tight", valueClass)}>
        {value}
      </span>
      {sub && (
        <span className="text-[11px] text-muted-foreground/55">{sub}</span>
      )}
    </div>
  );
}

export function KpiBar({
  stats,
  statsLoading,
  autoTradeEnabled,
  onAutoTradeToggle,
}: KpiBarProps) {
  const balance = useTradingStore((s) => s.balance);
  const openPositions = useTradingStore((s) => s.openPositions);

  const floatingPnl = openPositions.reduce((sum, p) => sum + (p.profit ?? 0), 0);
  const currency = balance?.currency ?? "USD";
  const fmt = (v: number) =>
    new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
      <KpiCard
        label="Balance"
        value={balance ? `${fmt(balance.balance)} ${currency}` : "—"}
      />
      <KpiCard
        label="Equity"
        value={balance ? `${fmt(balance.equity)} ${currency}` : "—"}
      />
      <KpiCard
        label="Floating P&L"
        value={`${floatingPnl >= 0 ? "+" : ""}${fmt(floatingPnl)} ${currency}`}
        valueClass={floatingPnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}
      />
      <KpiCard
        label="Win Rate"
        value={statsLoading ? "…" : stats ? pct(stats.win_rate) : "—"}
        sub={stats ? `${stats.winning_trades}/${stats.trade_count} trades` : undefined}
      />
      <KpiCard
        label="Total P&L"
        value={
          statsLoading ? "…"
            : stats
              ? `${stats.total_pnl >= 0 ? "+" : ""}${fmt(stats.total_pnl)} ${currency}`
              : "—"
        }
        valueClass={
          !statsLoading && stats
            ? stats.total_pnl >= 0
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-destructive"
            : undefined
        }
      />
      <KpiCard
        label="Free Margin"
        value={balance ? `${fmt(balance.free_margin)} ${currency}` : "—"}
      />
      <KpiCard
        label="Margin Level"
        value={balance?.margin_level != null ? `${fmt(balance.margin_level)}%` : "—"}
      />

      {/* Auto-Trade toggle */}
      <div className="card-surface p-4 flex flex-col justify-between gap-3">
        <span className="text-[11px] font-semibold text-muted-foreground/50 uppercase tracking-widest">
          Auto-Trade
        </span>
        <div className="flex items-center gap-2.5">
          <Switch
            checked={autoTradeEnabled}
            onCheckedChange={onAutoTradeToggle}
            aria-label={autoTradeEnabled ? "Disable auto-trade" : "Enable auto-trade"}
          />
          <span
            className={cn(
              "text-[13px] font-semibold",
              autoTradeEnabled ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground/50",
            )}
          >
            {autoTradeEnabled ? "ON" : "OFF"}
          </span>
        </div>
      </div>
    </div>
  );
}
