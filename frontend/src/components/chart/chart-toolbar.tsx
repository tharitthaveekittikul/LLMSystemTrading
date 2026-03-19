"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

const COUNTS = [200, 500, 1000] as const;
export type CandleCount = (typeof COUNTS)[number];

const TIMEZONES = [
  { label: "Local", value: "" },
  { label: "Bangkok", value: "Asia/Bangkok" },
  { label: "Singapore", value: "Asia/Singapore" },
  { label: "Tokyo", value: "Asia/Tokyo" },
  { label: "London", value: "Europe/London" },
  { label: "New York", value: "America/New_York" },
  { label: "UTC", value: "UTC" },
] as const;

const EMA_PERIODS = [20, 50, 200] as const;
export type EMAPeriod = (typeof EMA_PERIODS)[number];

const EMA_ACTIVE_STYLE: Record<EMAPeriod, string> = {
  20: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  50: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  200: "bg-blue-500/20 text-blue-400 border-blue-500/30",
};

interface ChartToolbarProps {
  symbol: string;
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  count: CandleCount;
  onCountChange: (n: CandleCount) => void;
  timezone?: string;
  onTimezoneChange?: (tz: string) => void;
  emaActive: EMAPeriod[];
  onEmaToggle: (p: EMAPeriod) => void;
  rsiActive: boolean;
  onRsiToggle: () => void;
  onRefresh?: () => void;
  isLoading?: boolean;
}

export function ChartToolbar({
  symbol,
  timeframe,
  onTimeframeChange,
  count,
  onCountChange,
  timezone,
  onTimezoneChange,
  emaActive,
  onEmaToggle,
  rsiActive,
  onRsiToggle,
  onRefresh,
  isLoading,
}: ChartToolbarProps) {
  const router = useRouter();
  const [input, setInput] = useState(symbol);

  function handleSymbolSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    const s = input.trim();
    if (s) router.push(`/chart/${s}`);
  }

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b bg-background shrink-0">
      {/* Symbol search */}
      <form onSubmit={handleSymbolSubmit} className="flex items-center gap-1.5">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            className="pl-8 h-8 w-32 text-sm font-mono"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="XAUUSD"
          />
        </div>
        <Button
          type="submit"
          size="sm"
          variant="secondary"
          className="h-8 px-3 text-xs font-semibold"
        >
          Go
        </Button>
      </form>

      <div className="h-5 w-px bg-border" />

      {/* Timeframe segmented control */}
      <div className="flex items-center bg-muted rounded-md p-0.5">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => onTimeframeChange(tf)}
            className={cn(
              "h-7 px-2.5 text-xs font-medium rounded transition-all",
              timeframe === tf
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-background/50",
            )}
          >
            {tf}
          </button>
        ))}
      </div>

      <div className="h-5 w-px bg-border" />

      {/* Candle count */}
      <div className="flex items-center bg-muted rounded-md p-0.5">
        {COUNTS.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onCountChange(n)}
            className={cn(
              "h-7 px-2.5 text-xs font-medium rounded transition-all",
              count === n
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-background/50",
            )}
          >
            {n}
          </button>
        ))}
      </div>

      {onTimezoneChange && (
        <>
          <div className="h-5 w-px bg-border" />
          <select
            className="h-7 px-2 text-xs font-medium rounded bg-muted text-muted-foreground hover:text-foreground cursor-pointer border-0 outline-none"
            value={timezone ?? ""}
            onChange={(e) => onTimezoneChange(e.target.value)}
          >
            {TIMEZONES.map((tz) => (
              <option key={tz.value} value={tz.value}>
                {tz.label}
              </option>
            ))}
          </select>
        </>
      )}

      <div className="h-5 w-px bg-border" />

      {/* Indicators */}
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-muted-foreground font-medium pr-0.5">EMA</span>
        {EMA_PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onEmaToggle(p)}
            className={cn(
              "h-7 px-2 text-xs font-medium rounded border transition-all",
              emaActive.includes(p)
                ? EMA_ACTIVE_STYLE[p]
                : "text-muted-foreground hover:text-foreground border-transparent",
            )}
          >
            {p}
          </button>
        ))}
        <button
          type="button"
          onClick={onRsiToggle}
          className={cn(
            "h-7 px-2 text-xs font-medium rounded border transition-all",
            rsiActive
              ? "bg-cyan-500/20 text-cyan-400 border-cyan-500/30"
              : "text-muted-foreground hover:text-foreground border-transparent",
          )}
        >
          RSI
        </button>
      </div>

      <div className="flex-1" />

      {/* Refresh */}
      {onRefresh && (
        <Button
          size="sm"
          variant="ghost"
          className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
          onClick={() => onRefresh()}
          disabled={isLoading}
          title="Refresh chart data"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
        </Button>
      )}
    </div>
  );
}
