"use client";

import { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { EquityPoint } from "@/types/trading";

interface EquityChartProps {
  data: EquityPoint[];
  loading: boolean;
}

export function EquityChart({ data, loading }: EquityChartProps) {
  const formatted = useMemo(
    () =>
      data.map((p) => ({
        ts: new Date(p.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        equity: p.equity,
        balance: p.balance,
      })),
    [data]
  );

  if (loading) {
    return (
      <div className="rounded-lg border bg-card p-4 h-48 flex items-center justify-center">
        <span className="text-sm text-muted-foreground">Loading equity history…</span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 h-48 flex items-center justify-center">
        <span className="text-sm text-muted-foreground">No equity data yet — starts after first MT5 poll (60s).</span>
      </div>
    );
  }

  const equityValues = data.map((p) => p.equity);
  const minEquity = Math.min(...equityValues);
  const maxEquity = Math.max(...equityValues);
  const padding = (maxEquity - minEquity) * 0.1 || 10;

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-medium mb-3">Equity Curve (24h)</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={formatted}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          <XAxis dataKey="ts" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis
            domain={[minEquity - padding, maxEquity + padding]}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => v.toLocaleString()}
            width={70}
          />
          <Tooltip
            formatter={(value: number) => [value.toLocaleString(), "Equity"]}
            labelFormatter={(label: string) => `Time: ${label}`}
          />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
