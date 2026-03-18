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

interface ChartToolbarProps {
  symbol: string;
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  count: CandleCount;
  onCountChange: (n: CandleCount) => void;
  timezone?: string;
  onTimezoneChange?: (tz: string) => void;
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
