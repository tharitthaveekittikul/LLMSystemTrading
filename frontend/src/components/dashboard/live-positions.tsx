"use client";

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
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-medium">Live Positions</CardTitle>
        <Badge variant="outline">{positions.length}</Badge>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open positions</p>
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
                    <Badge variant={pos.type === "buy" ? "default" : "secondary"}>
                      {pos.type.toUpperCase()}
                    </Badge>
                  </TableCell>
                  <TableCell>{pos.volume}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-medium",
                      pos.profit >= 0 ? "text-green-600" : "text-red-500",
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
