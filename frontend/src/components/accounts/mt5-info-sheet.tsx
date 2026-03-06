"use client";

import type { MT5AccountInfo } from "@/types/trading";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetBody,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useIsMobile } from "@/hooks/use-mobile";
import { TrendingDown, TrendingUp, Minus } from "lucide-react";

interface MT5InfoSheetProps {
  info: MT5AccountInfo | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MT5InfoSheet({ info, open, onOpenChange }: MT5InfoSheetProps) {
  const isMobile = useIsMobile();

  if (!info) return null;

  const tradeModeBadge =
    info.trade_mode === 2
      ? { label: "Live", variant: "destructive" as const }
      : info.trade_mode === 1
        ? { label: "Contest", variant: "secondary" as const }
        : { label: "Demo", variant: "outline" as const };

  const profit = info.profit ?? 0;
  const profitPositive = profit > 0;
  const profitNegative = profit < 0;
  const ProfitIcon = profitPositive
    ? TrendingUp
    : profitNegative
      ? TrendingDown
      : Minus;
  const profitColor = profitPositive
    ? "text-emerald-500"
    : profitNegative
      ? "text-red-500"
      : "text-muted-foreground";

  const body = (
    <MT5InfoBody
      info={info}
      tradeModeBadge={tradeModeBadge}
      profit={profit}
      profitColor={profitColor}
      ProfitIcon={ProfitIcon}
    />
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} direction="bottom">
        <DrawerContent className="max-h-[90vh]">
          <DrawerHeader className="border-b pb-4 text-left">
            <DrawerTitle className="flex items-center gap-2">
              MT5 Account Info
              <Badge variant={tradeModeBadge.variant}>
                {tradeModeBadge.label}
              </Badge>
            </DrawerTitle>
            <DrawerDescription>
              #{info.login} · {info.server}
            </DrawerDescription>
          </DrawerHeader>
          <div className="flex-1 overflow-y-auto px-4 py-4">{body}</div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            MT5 Account Info
            <Badge variant={tradeModeBadge.variant}>
              {tradeModeBadge.label}
            </Badge>
          </SheetTitle>
          <SheetDescription>
            #{info.login} · {info.server}
          </SheetDescription>
        </SheetHeader>
        <SheetBody>{body}</SheetBody>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Shared body content ─────────────────────────────────────────────── */

function MT5InfoBody({
  info,
  tradeModeBadge,
  profit,
  profitColor,
  ProfitIcon,
}: {
  info: MT5AccountInfo;
  tradeModeBadge: { label: string; variant: "destructive" | "secondary" | "outline" };
  profit: number;
  profitColor: string;
  ProfitIcon: React.ElementType;
}) {
  return (
    <div className="space-y-6">
      {/* ── Hero: Balance / Equity / P&L ── */}
      <div className="rounded-xl border bg-muted/30 p-4 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
              Balance
            </p>
            <p className="text-2xl font-bold tabular-nums">
              {info.balance.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </p>
            <p className="text-xs text-muted-foreground">{info.currency}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
              Equity
            </p>
            <p className="text-2xl font-bold tabular-nums">
              {info.equity.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </p>
            <p className="text-xs text-muted-foreground">{info.currency}</p>
          </div>
        </div>

        <Separator />

        {/* Floating P&L */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Floating P&amp;L
            </p>
            <p className={`text-xl font-bold tabular-nums ${profitColor}`}>
              {profit >= 0 ? "+" : ""}
              {profit.toFixed(2)} {info.currency}
            </p>
          </div>
          <div
            className={`rounded-full p-3 ${
              profit > 0
                ? "bg-emerald-500/10"
                : profit < 0
                  ? "bg-red-500/10"
                  : "bg-muted"
            }`}
          >
            <ProfitIcon
              className={`h-5 w-5 ${profitColor}`}
            />
          </div>
        </div>
      </div>

      {/* ── Risk / Margin ── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Margin
        </p>
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            label="Used"
            value={info.margin}
            currency={info.currency}
          />
          <StatCard
            label="Free"
            value={info.margin_free}
            currency={info.currency}
          />
          <div className="rounded-lg border bg-card p-3">
            <p className="text-xs text-muted-foreground mb-1">Level</p>
            <p className="text-base font-semibold tabular-nums">
              {info.margin_level != null
                ? `${info.margin_level.toFixed(1)}%`
                : "—"}
            </p>
          </div>
        </div>
      </div>

      {/* ── Account details ── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Account
        </p>
        <div className="rounded-xl border divide-y text-sm">
          {[
            { label: "Name", value: info.name },
            { label: "Company", value: info.company },
            { label: "Currency", value: info.currency },
            {
              label: "Leverage",
              value: `1:${info.leverage}`,
              mono: false,
            },
          ].map(({ label, value, mono }) => (
            <div key={label} className="flex justify-between px-4 py-2.5">
              <span className="text-muted-foreground">{label}</span>
              <span className={mono === false ? "" : "font-mono"}>{value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
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
    <div className="rounded-lg border bg-card p-3">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-base font-semibold tabular-nums">
        {value.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </p>
      <p className="text-xs text-muted-foreground">{currency}</p>
    </div>
  );
}
