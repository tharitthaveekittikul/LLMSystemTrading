"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { accountsApi } from "@/lib/api/accounts";
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
  activeAccountId: number | null;
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

/** Symbol search backed by the account's real broker symbol list (accountsApi.getSymbols),
 *  so picking one always lands on the exact broker-suffixed name (e.g. "XAUUSD.s")
 *  instead of a bare guess that MT5 may not recognize. */
function SymbolPicker({
  symbol,
  activeAccountId,
}: {
  symbol: string;
  activeAccountId: number | null;
}) {
  const router = useRouter();
  const [search, setSearch] = useState(symbol);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  // Reset the input's text when the route symbol changes (e.g. navigating to
  // a different /chart/[symbol]). Adjusting state during render — per React's
  // guidance — instead of an effect, so it can't cause a cascading extra render.
  const [prevSymbol, setPrevSymbol] = useState(symbol);
  if (symbol !== prevSymbol) {
    setPrevSymbol(symbol);
    setSearch(symbol);
  }

  useEffect(() => {
    if (!activeAccountId) return;
    let cancelled = false;
    setLoading(true);
    accountsApi
      .getSymbols(activeAccountId)
      .then((data) => {
        if (!cancelled) setSymbols(data);
      })
      .catch(() => {
        if (!cancelled) setSymbols([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeAccountId]);

  // No account selected → nothing to offer, regardless of whatever the last
  // fetch left in `symbols` (avoids clearing it via a synchronous effect).
  const availableSymbols = activeAccountId ? symbols : [];

  const filtered = useMemo(() => {
    if (!search || search === symbol) return availableSymbols;
    return availableSymbols.filter((s) => s.toLowerCase().includes(search.toLowerCase()));
  }, [availableSymbols, search, symbol]);

  function go(value: string) {
    const s = value.trim();
    if (s) router.push(`/chart/${s}`);
  }

  return (
    <Combobox
      value={symbol}
      onValueChange={(v) => {
        if (!v) return;
        setSearch(v);
        go(v);
      }}
    >
      <ComboboxInput
        placeholder={
          !activeAccountId
            ? "Select account first"
            : loading
              ? "Loading symbols…"
              : "Search symbol"
        }
        disabled={!activeAccountId}
        className="h-8 w-36 text-sm font-mono"
        aria-label="Chart symbol"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !availableSymbols.includes(search)) go(search);
        }}
      />
      <ComboboxContent className="min-w-[180px]">
        <ComboboxList>
          {filtered.map((s) => (
            <ComboboxItem key={s} value={s}>
              {s}
            </ComboboxItem>
          ))}
        </ComboboxList>
        <ComboboxEmpty>
          {activeAccountId ? "No matching symbols" : "Select an account first"}
        </ComboboxEmpty>
      </ComboboxContent>
    </Combobox>
  );
}

export function ChartToolbar({
  symbol,
  activeAccountId,
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
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2 border-b bg-background shrink-0">
      <SymbolPicker symbol={symbol} activeAccountId={activeAccountId} />

      <div className="h-5 w-px bg-border max-sm:hidden" />

      {/* Timeframe segmented control */}
      <div className="flex items-center bg-muted rounded-md p-0.5" role="group" aria-label="Timeframe">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            aria-pressed={timeframe === tf}
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

      <div className="h-5 w-px bg-border max-sm:hidden" />

      {/* Candle count */}
      <div className="flex items-center bg-muted rounded-md p-0.5" role="group" aria-label="Candle count">
        {COUNTS.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={count === n}
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

      <div className="h-5 w-px bg-border max-sm:hidden" />

      {/* Indicators */}
      <div className="flex items-center gap-1" role="group" aria-label="Indicators">
        <span className="text-[10px] text-muted-foreground font-medium pr-0.5">EMA</span>
        {EMA_PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={emaActive.includes(p)}
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
          aria-pressed={rsiActive}
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
