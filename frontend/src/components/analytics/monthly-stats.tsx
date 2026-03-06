"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DailyPnLResponse } from "@/types/trading";

interface MonthlyStatsProps {
  data: DailyPnLResponse | null;
  loading: boolean;
}

export function MonthlyStats({ data, loading }: MonthlyStatsProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">—</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-7 w-24 rounded bg-muted" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const pnl = data?.monthly_total ?? 0;
  const isProfit = pnl > 0;
  const isLoss = pnl < 0;
  const winningDays = data?.winning_days ?? 0;
  const losingDays = data?.losing_days ?? 0;
  const totalActiveDays = winningDays + losingDays;

  return (
    <div className="grid grid-cols-3 gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">
            Monthly PnL{data?.currency ? ` (${data.currency})` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p
            className={cn(
              "text-2xl font-bold",
              isProfit && "text-green-400",
              isLoss && "text-red-400",
              !isProfit && !isLoss && "text-muted-foreground",
            )}
          >
            {pnl > 0 ? "+" : ""}
            {pnl.toFixed(2)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Winning Days</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            <span className="text-green-400">{winningDays}</span>
            {totalActiveDays > 0 && (
              <span className="text-sm text-muted-foreground">
                {" "}/ {totalActiveDays}
              </span>
            )}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Total Trades</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {data?.monthly_trade_count ?? 0}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
