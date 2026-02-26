"use client";

import { BarChart2, DollarSign, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTradingStore } from "@/hooks/use-trading-store";

export function AccountOverview() {
  const balance = useTradingStore((s) => s.balance);

  const stats = [
    {
      label: "Balance",
      value: balance ? `$${balance.balance.toFixed(2)}` : "—",
      sub: balance?.currency ?? "",
      icon: DollarSign,
    },
    {
      label: "Equity",
      value: balance ? `$${balance.equity.toFixed(2)}` : "—",
      sub: balance
        ? balance.equity >= balance.balance
          ? "Profit"
          : "Drawdown"
        : "",
      icon:
        balance && balance.equity >= balance.balance ? TrendingUp : TrendingDown,
    },
    {
      label: "Free Margin",
      value: balance ? `$${balance.free_margin.toFixed(2)}` : "—",
      sub: balance?.margin_level
        ? `Level: ${balance.margin_level.toFixed(0)}%`
        : "",
      icon: BarChart2,
    },
  ];

  return (
    <>
      {stats.map((stat) => (
        <Card key={stat.label}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{stat.label}</CardTitle>
            <stat.icon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stat.value}</div>
            {stat.sub && (
              <p className="text-xs text-muted-foreground">{stat.sub}</p>
            )}
          </CardContent>
        </Card>
      ))}
    </>
  );
}
