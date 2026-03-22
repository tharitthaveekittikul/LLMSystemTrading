"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { backtestApi } from "@/lib/api";

interface DrawdownPoint {
  time: string;
  drawdown_pct: number;
}

interface Props {
  runId: number;
}

export function DrawdownChart({ runId }: Props) {
  const [data, setData] = useState<DrawdownPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    backtestApi
      .getDrawdown(runId)
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-muted-foreground text-xs">
        Loading drawdown...
      </div>
    );
  }

  if (data.length === 0) return null;

  const chartData = data.map((d) => ({
    time: d.time.slice(0, 10),
    drawdown_pct: d.drawdown_pct,
  }));

  return (
    <div className="space-y-2 mt-4">
      <h3 className="text-xs font-medium text-muted-foreground">Drawdown %</h3>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart
          data={chartData}
          margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0.05} />
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
            tick={{ fontSize: 9 }}
            tickLine={false}
            tickFormatter={(v: number) => `${v.toFixed(1)}%`}
            width={46}
            reversed
          />
          <Tooltip
            formatter={(value: number) => [`${value.toFixed(2)}%`, "Drawdown"]}
            labelStyle={{ fontSize: 10 }}
            contentStyle={{ fontSize: 10 }}
          />
          <Area
            type="monotone"
            dataKey="drawdown_pct"
            stroke="#ef4444"
            fill="url(#drawdownGradient)"
            strokeWidth={1.5}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
