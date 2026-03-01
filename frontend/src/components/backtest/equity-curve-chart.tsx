"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BacktestEquityPoint } from "@/types/trading";

interface Props {
  data: BacktestEquityPoint[];
  initialBalance: number;
}

export function EquityCurveChart({ data, initialBalance }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-xs text-muted-foreground">
        No trade data
      </div>
    );
  }

  const chartData = [
    { time: data[0].time.slice(0, 10), equity: initialBalance },
    ...data.map((d) => ({ time: d.time.slice(0, 10), equity: d.equity })),
  ];

  const values = chartData.map((d) => d.equity);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const padding = (maxVal - minVal) * 0.05 || 100;

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart
        data={chartData}
        margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
      >
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="5%"
              stopColor="hsl(var(--primary))"
              stopOpacity={0.15}
            />
            <stop
              offset="95%"
              stopColor="hsl(var(--primary))"
              stopOpacity={0}
            />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          dataKey="time"
          tick={{ fontSize: 9 }}
          tickLine={false}
          tickFormatter={(v: string) => v.slice(0, 7)}
          interval="preserveStartEnd"
        />
        <YAxis
          domain={[minVal - padding, maxVal + padding]}
          tick={{ fontSize: 9 }}
          tickLine={false}
          tickFormatter={(v: number) => `$${v.toLocaleString()}`}
          width={70}
        />
        <Tooltip
          formatter={(v: number) => [`$${v.toLocaleString()}`, "Equity"]}
          labelStyle={{ fontSize: 10 }}
          contentStyle={{ fontSize: 10 }}
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="hsl(var(--primary))"
          fill="url(#eqGrad)"
          strokeWidth={1.5}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
