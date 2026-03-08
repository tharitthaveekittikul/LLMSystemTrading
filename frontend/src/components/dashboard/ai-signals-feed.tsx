"use client";

import { formatDateTime } from "@/lib/date";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from "@/hooks/use-trading-store";
import { cn } from "@/lib/utils";
import type { AISignal } from "@/types/trading";

const actionVariant: Record<
  AISignal["signal"],
  "default" | "secondary" | "outline"
> = {
  BUY: "default",
  SELL: "secondary",
  BUY_LIMIT: "default",
  SELL_LIMIT: "secondary",
  BUY_STOP: "default",
  SELL_STOP: "secondary",
  HOLD: "outline",
};

export function AISignalsFeed() {
  const signals = useTradingStore((s) => s.recentSignals);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">AI Signals</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[300px] overflow-y-auto">
          {signals.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recent signals</p>
          ) : (
            <div className="space-y-3">
              {signals.map((signal) => (
                <div
                  key={signal.id}
                  className="flex items-start justify-between gap-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant={actionVariant[signal.signal]}>
                      {signal.signal}
                    </Badge>
                    <span className="font-medium">{signal.symbol}</span>
                  </div>
                  <div className="text-right">
                    <div
                      className={cn(
                        "text-xs font-medium",
                        signal.confidence >= 0.7
                          ? "text-green-600"
                          : signal.confidence >= 0.5
                            ? "text-yellow-600"
                            : "text-muted-foreground",
                      )}
                    >
                      {(signal.confidence * 100).toFixed(0)}%
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {formatDateTime(signal.created_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
