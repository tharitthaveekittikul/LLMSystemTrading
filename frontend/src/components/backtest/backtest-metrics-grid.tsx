import { cn } from "@/lib/utils";
import type { BacktestRunSummary } from "@/types/trading";

interface Props {
  run: BacktestRunSummary;
}

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-3 text-center">
      <div className={cn("text-base font-bold tabular-nums", color)}>
        {value}
      </div>
      <div className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
        {label}
      </div>
    </div>
  );
}

function fmt(
  v: number | null | undefined,
  decimals = 2,
  suffix = "",
): string {
  if (v == null) return "—";
  return `${v.toFixed(decimals)}${suffix}`;
}

export function BacktestMetricsGrid({ run }: Props) {
  const returnColor =
    (run.total_return_pct ?? 0) >= 0 ? "text-green-600" : "text-red-500";

  return (
    <div className="grid grid-cols-4 gap-2">
      <MetricCard
        label="Total Return"
        value={fmt(run.total_return_pct, 2, "%")}
        color={returnColor}
      />
      <MetricCard
        label="Win Rate"
        value={
          run.win_rate != null
            ? `${(run.win_rate * 100).toFixed(1)}%`
            : "—"
        }
      />
      <MetricCard
        label="Profit Factor"
        value={fmt(run.profit_factor)}
      />
      <MetricCard
        label="Max Drawdown"
        value={fmt(run.max_drawdown_pct, 2, "%")}
        color="text-red-500"
      />
      <MetricCard
        label="Recovery Factor"
        value={fmt(run.recovery_factor)}
      />
      <MetricCard label="Sharpe Ratio" value={fmt(run.sharpe_ratio)} />
      <MetricCard label="Sortino Ratio" value={fmt(run.sortino_ratio)} />
      <MetricCard label="Expectancy ($)" value={fmt(run.expectancy)} />
      <MetricCard
        label="Total Trades"
        value={run.total_trades != null ? String(run.total_trades) : "—"}
      />
      <MetricCard
        label="Avg Win ($)"
        value={fmt(run.avg_win)}
        color="text-green-600"
      />
      <MetricCard
        label="Avg Loss ($)"
        value={fmt(run.avg_loss)}
        color="text-red-500"
      />
      <MetricCard
        label="Max Consec Wins"
        value={
          run.max_consec_wins != null ? String(run.max_consec_wins) : "—"
        }
      />
      {run.avg_spread != null && run.avg_spread > 0 && (
        <MetricCard
          label="Avg Spread (pts)"
          value={run.avg_spread.toFixed(1)}
        />
      )}
    </div>
  );
}
