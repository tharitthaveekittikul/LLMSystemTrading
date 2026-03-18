"use client";

import { useMemo } from "react";
import { formatTime, formatDateTime } from "@/lib/date";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import type { EquityPoint } from "@/types/trading";

const RANGES = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
  // { label: "30d", hours: 720 },
  // { label: "90d", hours: 2160 },
  // { label: "180d", hours: 4320 },
  // { label: "365d", hours: 8760 },
  // { label: "All", hours: 0 },
] as const;

interface EquityChartProps {
  data: EquityPoint[];
  loading: boolean;
  hours: number;
  onHoursChange: (hours: number) => void;
}

export function EquityChart({
  data,
  loading,
  hours,
  onHoursChange,
}: EquityChartProps) {
  const formatted = useMemo(
    () =>
      data.map((p) => ({
        ts: p.ts,
        equity: p.equity,
        balance: p.balance,
      })),
    [data],
  );

  const rangeBar = (
    <div className="flex rounded-md border overflow-hidden">
      {RANGES.map((r) => (
        <button
          key={r.hours}
          onClick={() => onHoursChange(r.hours)}
          className={`px-2 py-0.5 text-xs transition-colors ${
            hours === r.hours
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted"
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );

  if (loading) {
    return (
      <div className="rounded-lg border bg-card p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Equity Curve</h3>
          {rangeBar}
        </div>
        <div className="h-[220px] flex items-center justify-center">
          <span className="text-sm text-muted-foreground">
            Loading equity history…
          </span>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Equity Curve</h3>
          {rangeBar}
        </div>
        <div className="h-[220px] flex items-center justify-center">
          <span className="text-sm text-muted-foreground">
            No equity data yet — starts after first MT5 poll (60s).
          </span>
        </div>
      </div>
    );
  }

  const equityValues = data.map((p) => p.equity);
  const balanceValue = data[data.length - 1]?.balance;
  const minEquity = Math.min(...equityValues);
  const maxEquity = Math.max(...equityValues);
  const padding = (maxEquity - minEquity) * 0.1 || 10;

  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">Equity Curve</h3>
        <div className="flex items-center gap-3">
          {balanceValue != null && (
            <span className="text-xs text-muted-foreground">
              Balance: {balanceValue.toLocaleString()}
            </span>
          )}
          {rangeBar}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={formatted}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis
            dataKey="ts"
            tickFormatter={(v: string) => formatTime(v)}
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[minEquity - padding, maxEquity + padding]}
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            tickFormatter={(v: number) => v.toLocaleString()}
            width={70}
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-popover)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-md)",
              fontSize: "0.75rem",
            }}
            labelStyle={{ color: "var(--color-muted-foreground)" }}
            formatter={(value: number) => [value.toLocaleString(), "Equity"]}
            labelFormatter={(label: string) => formatDateTime(label)}
          />
          {balanceValue != null && (
            <ReferenceLine
              y={balanceValue}
              stroke="var(--color-muted-foreground)"
              strokeDasharray="4 4"
              strokeOpacity={0.6}
              label={{
                value: "Balance",
                position: "insideTopRight",
                fontSize: 10,
                fill: "var(--color-muted-foreground)",
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="equity"
            stroke="var(--color-primary)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "var(--color-primary)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
