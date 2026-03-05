"use client";

import { Inbox } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from "@/hooks/use-trading-store";
import { cn } from "@/lib/utils";

export function LivePositions() {
  const positions = useTradingStore((s) => s.openPositions);

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-medium">Live Positions</CardTitle>
        <Badge
          variant={positions.length > 0 ? "default" : "outline"}
          className="tabular-nums"
        >
          {positions.length}
        </Badge>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
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
                <TableHead className="text-right">P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((pos) => (
                <TableRow key={pos.ticket}>
                  <TableCell className="font-medium">{pos.symbol}</TableCell>
                  <TableCell>
                    <Badge
                      className={cn(
                        "text-xs font-medium border-0",
                        pos.type === "buy"
                          ? "bg-green-500 hover:bg-green-600 text-white"
                          : "bg-red-500 hover:bg-red-600 text-white",
                      )}
                    >
                      {pos.type.toUpperCase()}
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
