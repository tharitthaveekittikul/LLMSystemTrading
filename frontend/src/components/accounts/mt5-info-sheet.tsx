"use client";

import type { MT5AccountInfo } from "@/types/trading";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

interface MT5InfoSheetProps {
  info: MT5AccountInfo | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MT5InfoSheet({ info, open, onOpenChange }: MT5InfoSheetProps) {
  if (!info) return null;

  const tradeModeBadge =
    info.trade_mode === 2
      ? { label: "Live", variant: "destructive" as const }
      : info.trade_mode === 1
        ? { label: "Contest", variant: "secondary" as const }
        : { label: "Demo", variant: "outline" as const };

  const profitColor =
    info.profit > 0
      ? "text-green-600"
      : info.profit < 0
        ? "text-red-600"
        : "text-muted-foreground";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[400px] sm:w-[480px]">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            MT5 Account Info
            <Badge variant={tradeModeBadge.variant}>{tradeModeBadge.label}</Badge>
          </SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4">
          {/* Identity */}
          <div className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Login</span>
              <span className="font-mono">{info.login}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Name</span>
              <span>{info.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Server</span>
              <span>{info.server}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Company</span>
              <span>{info.company}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Currency</span>
              <span>{info.currency}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Leverage</span>
              <span>1:{info.leverage}</span>
            </div>
          </div>

          <Separator />

          {/* Balance stats */}
          <div className="grid grid-cols-2 gap-3">
            <StatCard label="Balance" value={info.balance} currency={info.currency} />
            <StatCard label="Equity" value={info.equity} currency={info.currency} />
            <StatCard label="Margin" value={info.margin} currency={info.currency} />
            <StatCard label="Free Margin" value={info.margin_free} currency={info.currency} />
          </div>

          <Separator />

          <div className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Margin Level</span>
              <span>
                {info.margin_level != null ? `${info.margin_level.toFixed(2)}%` : "—"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Floating P&L</span>
              <span className={`font-semibold ${profitColor}`}>
                {info.profit >= 0 ? "+" : ""}
                {info.profit.toFixed(2)} {info.currency}
              </span>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function StatCard({
  label,
  value,
  currency,
}: {
  label: string;
  value: number;
  currency: string;
}) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">
        {value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </p>
      <p className="text-xs text-muted-foreground">{currency}</p>
    </div>
  );
}
