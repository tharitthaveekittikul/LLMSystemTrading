"use client";

import { useState } from "react";
import { Inbox, Wrench } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { schedulerApi } from "@/lib/api";
import { useTradingStore } from "@/hooks/use-trading-store";
import { cn } from "@/lib/utils";

const ORDER_TYPE_COLORS: Record<string, string> = {
  buy:             "bg-green-500 hover:bg-green-600 text-white",
  sell:            "bg-red-500 hover:bg-red-600 text-white",
  buy_limit:       "bg-emerald-400 hover:bg-emerald-500 text-white",
  sell_limit:      "bg-orange-400 hover:bg-orange-500 text-white",
  buy_stop:        "bg-teal-500 hover:bg-teal-600 text-white",
  sell_stop:       "bg-rose-500 hover:bg-rose-600 text-white",
  buy_stop_limit:  "bg-cyan-500 hover:bg-cyan-600 text-white",
  sell_stop_limit: "bg-pink-500 hover:bg-pink-600 text-white",
};

function orderTypeLabel(type: string): string {
  return type.replace(/_/g, " ").toUpperCase();
}

export function LivePositions() {
  const positions = useTradingStore((s) => s.openPositions);
  const pendingOrders = useTradingStore((s) => s.pendingOrders);
  const [runningTicket, setRunningTicket] = useState<number | null>(null);

  const totalCount = positions.length + pendingOrders.length;
  const isEmpty = totalCount === 0;

  async function handleRunMaintenance(accountId: number, ticket: number) {
    setRunningTicket(ticket);
    try {
      await schedulerApi.runMaintenanceForTicket(accountId, ticket);
      toast.success(`Maintenance started for ticket #${ticket}`);
    } catch {
      toast.error("Failed to trigger maintenance");
    } finally {
      setRunningTicket(null);
    }
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-medium">Live Positions</CardTitle>
        <Badge
          variant={totalCount > 0 ? "default" : "outline"}
          className="tabular-nums"
        >
          {totalCount}
        </Badge>
      </CardHeader>
      <CardContent>
        {isEmpty ? (
          <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
            <Inbox className="h-8 w-8 opacity-40" />
            <span className="text-sm">No open positions</span>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Volume</TableHead>
                <TableHead className="text-right">Price / P&amp;L</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((pos) => (
                <TableRow key={`pos-${pos.ticket}`}>
                  <TableCell className="font-medium">{pos.symbol}</TableCell>
                  <TableCell>
                    <Badge
                      className={cn(
                        "text-xs font-medium border-0",
                        ORDER_TYPE_COLORS[pos.type] ?? ORDER_TYPE_COLORS.buy,
                      )}
                    >
                      {orderTypeLabel(pos.type)}
                    </Badge>
                  </TableCell>
                  <TableCell>{pos.volume}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-medium tabular-nums",
                      pos.profit >= 0
                        ? "text-green-600 dark:text-green-400"
                        : "text-red-500",
                    )}
                  >
                    {pos.profit >= 0 ? "+" : ""}
                    {pos.profit.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      title="Run maintenance for this position"
                      disabled={runningTicket === pos.ticket}
                      onClick={() => handleRunMaintenance(pos.account_id, pos.ticket)}
                    >
                      <Wrench className="h-3.5 w-3.5" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {pendingOrders.map((order) => (
                <TableRow key={`order-${order.ticket}`} className="opacity-70">
                  <TableCell className="font-medium">{order.symbol}</TableCell>
                  <TableCell>
                    <Badge
                      className={cn(
                        "text-xs font-medium border-0",
                        ORDER_TYPE_COLORS[order.type] ?? "bg-muted text-muted-foreground",
                      )}
                    >
                      {orderTypeLabel(order.type)}
                    </Badge>
                  </TableCell>
                  <TableCell>{order.volume}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    @ {order.price}
                  </TableCell>
                  <TableCell />
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
