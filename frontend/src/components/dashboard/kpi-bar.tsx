"use client";

import { useTradingStore } from "@/hooks/use-trading-store";
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
    <div className="rounded-lg border bg-card p-3 flex flex-col gap-1 shadow-sm">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={`text-lg font-semibold tabular-nums ${valueClass ?? ""}`}
      >
        {value}
      </span>
      {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
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

  const floatingPnl = openPositions.reduce(
    (sum, p) => sum + (p.profit ?? 0),
    0,
  );
  const currency = balance?.currency ?? "USD";
  const fmt = (v: number) =>
    new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(v);
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
        valueClass={
          floatingPnl >= 0
            ? "text-green-600 dark:text-green-400"
            : "text-red-500"
        }
      />
      <KpiCard
        label="Win Rate"
        value={statsLoading ? "…" : stats ? pct(stats.win_rate) : "—"}
        sub={
          stats
            ? `${stats.winning_trades}/${stats.trade_count} trades`
            : undefined
        }
      />
      <KpiCard
        label="Total P&L"
        value={
          statsLoading
            ? "…"
            : stats
              ? `${stats.total_pnl >= 0 ? "+" : ""}${fmt(stats.total_pnl)} ${currency}`
              : "—"
        }
        valueClass={
          !statsLoading && stats
            ? stats.total_pnl >= 0
              ? "text-green-600 dark:text-green-400"
              : "text-red-500"
            : undefined
        }
      />
      <KpiCard
        label="Free Margin"
        value={balance ? `${fmt(balance.free_margin)} ${currency}` : "—"}
      />
      <KpiCard
        label="Margin Level"
        value={
          balance?.margin_level != null ? `${fmt(balance.margin_level)}%` : "—"
        }
      />
      {/* Auto-Trade toggle */}
      <div className="rounded-lg border bg-card p-3 flex flex-col justify-between shadow-sm">
        <span className="text-xs text-muted-foreground">Auto-Trade</span>
        <div className="flex items-center gap-2 mt-2">
          <button
            onClick={() => onAutoTradeToggle(!autoTradeEnabled)}
            aria-label={
              autoTradeEnabled ? "Disable auto-trade" : "Enable auto-trade"
            }
            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${
              autoTradeEnabled ? "bg-green-500" : "bg-muted-foreground/30"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                autoTradeEnabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
          <span
            className={`text-sm font-semibold ${
              autoTradeEnabled
                ? "text-green-600 dark:text-green-400"
                : "text-muted-foreground"
            }`}
          >
            {autoTradeEnabled ? "ON" : "OFF"}
          </span>
        </div>
      </div>
    </div>
  );
}
