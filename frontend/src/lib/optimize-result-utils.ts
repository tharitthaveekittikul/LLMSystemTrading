export const PAGE_SIZE = 50;

export const METRIC_LABELS: Record<string, string> = {
  sharpe_ratio: "Sharpe",
  profit_factor: "Profit Factor",
  total_return_pct: "Return %",
  win_rate: "Win Rate",
  expectancy: "Expectancy",
  max_drawdown_pct: "Max DD %",
  recovery_factor: "Recovery",
  sortino_ratio: "Sortino",
};

// ── Quality thresholds ("Good" tier) ──────────────────────────────────────
export const THRESHOLDS: Record<string, { value: number; lowerIsBetter: boolean; label: string }> = {
  sharpe_ratio:     { value: 1.5,  lowerIsBetter: false, label: "Sharpe ≥ 1.5"   },
  profit_factor:    { value: 1.75, lowerIsBetter: false, label: "PF ≥ 1.75"       },
  win_rate:         { value: 0.55, lowerIsBetter: false, label: "Win ≥ 55%"       },
  max_drawdown_pct: { value: 20,   lowerIsBetter: true,  label: "MDD ≤ 20%"       },
  recovery_factor:  { value: 2.0,  lowerIsBetter: false, label: "RF ≥ 2.0"        },
  total_return_pct: { value: 10,   lowerIsBetter: false, label: "Return ≥ 10%"    },
  total_trades:     { value: 20,   lowerIsBetter: false, label: "Trades ≥ 20"     },
};

export function qualityScore(metrics: { [key: string]: number | null }): { passed: number; total: number; allPassed: boolean } {
  let passed = 0;
  const total = Object.keys(THRESHOLDS).length;
  for (const [key, t] of Object.entries(THRESHOLDS)) {
    const v = metrics[key];
    if (v == null) continue;
    if (t.lowerIsBetter ? v <= t.value : v >= t.value) passed++;
  }
  return { passed, total, allPassed: passed === total };
}

export const ALL_METRICS = [
  "total_trades",
  "win_rate",
  "profit_factor",
  "sharpe_ratio",
  "sortino_ratio",
  "total_return_pct",
  "expectancy",
  "max_drawdown_pct",
  "recovery_factor",
  "avg_win",
  "avg_loss",
] as const;

export function fmt(val: number | null | undefined, key: string): string {
  if (val == null) return "—";
  if (key === "win_rate") return `${(val * 100).toFixed(1)}%`;
  if (key === "total_return_pct" || key === "max_drawdown_pct") return `${val.toFixed(2)}%`;
  return val.toFixed(3);
}

export function fmtEta(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function fmtElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (seconds < 3600) return `${m}m ${s}s`;
  const h = Math.floor(seconds / 3600);
  const rem = Math.floor((seconds % 3600) / 60);
  return `${h}h ${rem}m`;
}

export function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function dataDays(start: string, end: string): number {
  return Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86_400_000);
}
