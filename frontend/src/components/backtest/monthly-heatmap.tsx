"use client";

import { cn } from "@/lib/utils";
import type { BacktestMonthlyPnl } from "@/types/trading";

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

interface Props {
  data: BacktestMonthlyPnl[];
}

export function MonthlyHeatmap({ data }: Props) {
  if (data.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-4">
        No monthly data
      </p>
    );
  }

  const years = [...new Set(data.map((d) => d.year))].sort();
  const byKey = new Map(data.map((d) => [`${d.year}-${d.month}`, d]));
  const maxAbs = Math.max(...data.map((d) => Math.abs(d.pnl)), 1);

  function cellColor(pnl: number | null): string {
    if (pnl == null) return "bg-muted/30";
    const intensity = Math.min(Math.abs(pnl) / maxAbs, 1);
    if (pnl > 0) {
      if (intensity > 0.75) return "bg-green-600 text-white";
      if (intensity > 0.5) return "bg-green-500 text-white";
      if (intensity > 0.25) return "bg-green-400";
      return "bg-green-200";
    } else {
      if (intensity > 0.75) return "bg-red-600 text-white";
      if (intensity > 0.5) return "bg-red-500 text-white";
      if (intensity > 0.25) return "bg-red-400";
      return "bg-red-200";
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-[10px] border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className="w-10 text-left text-muted-foreground pr-2 font-medium">
              Year
            </th>
            {MONTHS.map((m) => (
              <th
                key={m}
                className="w-10 text-center text-muted-foreground font-medium"
              >
                {m}
              </th>
            ))}
            <th className="w-12 text-right text-muted-foreground font-medium pl-1">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => {
            const yearTotal = MONTHS.reduce((sum, _, mi) => {
              const entry = byKey.get(`${year}-${mi + 1}`);
              return sum + (entry?.pnl ?? 0);
            }, 0);
            return (
              <tr key={year}>
                <td className="pr-2 text-muted-foreground font-medium">
                  {year}
                </td>
                {MONTHS.map((_, mi) => {
                  const entry = byKey.get(`${year}-${mi + 1}`);
                  const pnl = entry?.pnl ?? null;
                  return (
                    <td
                      key={mi}
                      title={
                        pnl != null
                          ? `${year}-${MONTHS[mi]}: $${pnl.toFixed(2)} (${entry?.trade_count} trades)`
                          : "No trades"
                      }
                      className={cn(
                        "w-10 h-7 rounded text-center cursor-default",
                        cellColor(pnl),
                      )}
                    >
                      {pnl != null && (
                        <span className="text-[9px] font-medium">
                          {pnl >= 0 ? "+" : ""}
                          {pnl.toFixed(0)}
                        </span>
                      )}
                    </td>
                  );
                })}
                <td
                  className={cn(
                    "pl-1 text-right font-medium",
                    yearTotal >= 0 ? "text-green-600" : "text-red-500",
                  )}
                >
                  {yearTotal >= 0 ? "+" : ""}
                  {yearTotal.toFixed(0)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
