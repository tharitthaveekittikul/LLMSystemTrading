"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { optimizationApi, API_BASE_URL } from "@/lib/api";
import type { StrategyRegistryEntry } from "@/types/trading";

/** Parse MT5 tab-separated CSV to extract start/end date strings (YYYY-MM-DD). */
function parseMt5CsvDates(file: File): Promise<{ startDate: string; endDate: string } | null> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string;
        const dataLines = text.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("<"));
        if (dataLines.length === 0) { resolve(null); return; }
        const toDate = (line: string) => line.split("\t")[0]?.replace(/\./g, "-") ?? null;
        const start = toDate(dataLines[0]);
        const end = toDate(dataLines[dataLines.length - 1]);
        resolve(start && end ? { startDate: start, endDate: end } : null);
      } catch { resolve(null); }
    };
    reader.onerror = () => resolve(null);
    reader.readAsText(file);
  });
}

interface StrategyItem {
  id: number;
  name: string;
  primary_tf: string;
  context_tfs: string[];
  strategy_key: string | null;
}

interface ParamField {
  name: string;
  label: string;
  type: "int" | "float" | "bool" | "str" | "select";
  default: number | string | boolean;
  min?: number;
  max?: number;
  step?: number;
  optimize?: boolean;
}

/** One row in the sweep builder: the user defines the values to try for a param */
interface SweepRow {
  name: string;
  label: string;
  type: "int" | "float";
  enabled: boolean;
  mode: "range" | "list"; // range = min/max/step; list = comma-separated values
  min: string;
  max: string;
  step: string;
  list: string; // comma-separated
}

const METRICS = [
  { value: "sharpe_ratio", label: "Sharpe Ratio" },
  { value: "profit_factor", label: "Profit Factor" },
  { value: "total_return_pct", label: "Total Return %" },
  { value: "win_rate", label: "Win Rate" },
  { value: "expectancy", label: "Expectancy" },
  { value: "max_drawdown_pct", label: "Max Drawdown % (lower = better)" },
  { value: "recovery_factor", label: "Recovery Factor" },
  { value: "sortino_ratio", label: "Sortino Ratio" },
];

function generateRange(
  min: number,
  max: number,
  step: number,
  isInt: boolean,
): number[] {
  const values: number[] = [];
  let cur = min;
  while (cur <= max + 1e-9) {
    values.push(isInt ? Math.round(cur) : parseFloat(cur.toFixed(6)));
    cur += step;
    if (values.length > 50) break; // safety cap
  }
  return [...new Set(values)];
}

function parseList(raw: string, isInt: boolean): number[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => (isInt ? parseInt(s, 10) : parseFloat(s)))
    .filter((v) => !isNaN(v));
}

export default function NewOptimizePage() {
  const router = useRouter();

  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [strategyId, setStrategyId] = useState<string>("");
  const [registryParams, setRegistryParams] = useState<ParamField[]>([]);
  const [sweepRows, setSweepRows] = useState<SweepRow[]>([]);

  const [symbol, setSymbol] = useState("XAUUSD.s");
  const [startDate, setStartDate] = useState("2017-01-02");
  const [endDate, setEndDate] = useState("2023-12-29");
  const [balance, setBalance] = useState("10000");
  const [spread, setSpread] = useState("1.5");
  const [volume, setVolume] = useState("0.1");
  const [sizingMode, setSizingMode] = useState<"fixed" | "risk">("fixed");
  const [riskPct, setRiskPct] = useState("1"); // percentage, e.g. "1" = 1%
  const [mode, setMode] = useState<"close_price" | "intra_candle">(
    "close_price",
  );
  const [metric, setMetric] = useState("sharpe_ratio");
  const [commissionPerLot, setCommissionPerLot] = useState("0");
  const [tpPartialCloseRatio, setTpPartialCloseRatio] = useState("0.5");
  const [maxWorkers, setMaxWorkers] = useState("4");

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [contextCsvFiles, setContextCsvFiles] = useState<Record<string, File | null>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load strategies list
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/strategies`);
        const data: StrategyItem[] = await res.json();
        setStrategies(Array.isArray(data) ? data : []);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const selectedStrategy = strategies.find((s) => String(s.id) === strategyId);
  // Exclude primary TF from context list (it's uploaded separately as primary CSV)
  const contextTfs = (selectedStrategy?.context_tfs ?? []).filter(
    (tf) => tf !== selectedStrategy?.primary_tf,
  );

  // When strategy changes, fetch its registry params
  useEffect(() => {
    setContextCsvFiles({});
    if (!strategyId) {
      setRegistryParams([]);
      setSweepRows([]);
      return;
    }
    const strat = strategies.find((s) => String(s.id) === strategyId);
    if (!strat?.strategy_key) {
      setRegistryParams([]);
      setSweepRows([]);
      return;
    }

    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/strategies/registry`);
        const all: StrategyRegistryEntry[] = await res.json();
        const entry = all.find((e) => e.key === strat.strategy_key);
        if (!entry) return;

        const numericParams = (entry.params as ParamField[]).filter(
          (p) => (p.type === "int" || p.type === "float") && p.optimize,
        );
        setRegistryParams(numericParams);

        setSweepRows(
          numericParams.map((p) => ({
            name: p.name,
            label: p.label,
            type: p.type as "int" | "float",
            enabled: false,
            mode: "range",
            min: String(p.min ?? p.default),
            max: String(p.max ?? p.default),
            step: String(p.step ?? (p.type === "int" ? 1 : 0.1)),
            list: String(p.default),
          })),
        );
      } catch {
        /* ignore */
      }
    })();
  }, [strategyId, strategies]);

  const updateRow = (idx: number, patch: Partial<SweepRow>) => {
    setSweepRows((prev) =>
      prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    );
  };

  const computedCombinations = sweepRows.reduce((total, row) => {
    if (!row.enabled) return total;
    const isInt = row.type === "int";
    const vals =
      row.mode === "range"
        ? generateRange(
            parseFloat(row.min),
            parseFloat(row.max),
            parseFloat(row.step),
            isInt,
          )
        : parseList(row.list, isInt);
    return total * Math.max(vals.length, 1);
  }, 1);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!strategyId) {
      setError("Please select a strategy");
      return;
    }

    const enabledRows = sweepRows.filter((r) => r.enabled);
    if (enabledRows.length === 0) {
      setError("Enable at least one parameter to sweep");
      return;
    }

    const param_grid: Record<string, number[]> = {};
    for (const row of enabledRows) {
      const isInt = row.type === "int";
      const vals =
        row.mode === "range"
          ? generateRange(
              parseFloat(row.min),
              parseFloat(row.max),
              parseFloat(row.step),
              isInt,
            )
          : parseList(row.list, isInt);
      if (vals.length === 0) {
        setError(`No valid values for "${row.label}"`);
        return;
      }
      param_grid[row.name] = vals;
    }

    if (computedCombinations > 100000) {
      setError(
        `Too many combinations (${computedCombinations}). Reduce ranges to ≤ 100000.`,
      );
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      let csvUploadId: string | undefined;
      if (csvFile) {
        const r = await optimizationApi.uploadCsv(csvFile);
        csvUploadId = r.upload_id;
      }

      // Upload context TF CSVs if provided
      let csvUploads: Record<string, string> | undefined;
      const ctxEntries = Object.entries(contextCsvFiles).filter(([, f]) => f != null);
      if (ctxEntries.length > 0) {
        csvUploads = {};
        for (const [tf, file] of ctxEntries) {
          if (file) {
            const r = await optimizationApi.uploadCsv(file);
            csvUploads[tf] = r.upload_id;
          }
        }
      }

      const run = await optimizationApi.submit({
        strategy_id: Number(strategyId),
        symbol,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        initial_balance: Number(balance),
        spread_pips: Number(spread),
        execution_mode: mode,
        volume: Number(volume),
        risk_pct: sizingMode === "risk" ? Number(riskPct) / 100 : null,
        commission_per_lot: Number(commissionPerLot),
        tp_partial_close_ratio: Number(tpPartialCloseRatio),
        max_workers: Number(maxWorkers),
        csv_upload_id: csvUploadId,
        csv_uploads: csvUploads,
        param_grid,
        optimize_metric: metric,
      });
      router.push(`/backtest/optimize/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SidebarInset>
      <AppHeader
        title="New Optimization"
        subtitle="Configure parameter sweep"
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="p-5 max-w-2xl space-y-6">
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* ── Strategy ── */}
          <section className="space-y-3">
            <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
              Strategy
            </h2>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Strategy</Label>
                <Select value={strategyId} onValueChange={setStrategyId}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="Select strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies.map((s) => (
                      <SelectItem
                        key={s.id}
                        value={String(s.id)}
                        className="text-xs"
                      >
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Symbol</Label>
                <Input
                  className="h-8 text-xs"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Optimize Metric</Label>
                <Select value={metric} onValueChange={setMetric}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {METRICS.map((m) => (
                      <SelectItem
                        key={m.value}
                        value={m.value}
                        className="text-xs"
                      >
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </section>

          {/* ── Date & Balance ── */}
          <section className="space-y-3">
            <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
              Date Range & Capital
            </h2>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Start Date</Label>
                <Input
                  type="date"
                  className="h-8 text-xs"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">End Date</Label>
                <Input
                  type="date"
                  className="h-8 text-xs"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Initial Balance ($)</Label>
                <Input
                  className="h-8 text-xs"
                  value={balance}
                  onChange={(e) => setBalance(e.target.value)}
                />
              </div>
              {/* Sizing mode toggle */}
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Position Sizing</Label>
                <div className="flex gap-1">
                  <Button
                    type="button"
                    size="sm"
                    variant={sizingMode === "fixed" ? "default" : "outline"}
                    className="h-7 text-xs px-3"
                    onClick={() => setSizingMode("fixed")}
                  >
                    Fixed Lot
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={sizingMode === "risk" ? "default" : "outline"}
                    className="h-7 text-xs px-3"
                    onClick={() => setSizingMode("risk")}
                  >
                    Risk %
                  </Button>
                </div>
              </div>
              {sizingMode === "fixed" ? (
                <div className="space-y-1">
                  <Label className="text-xs">Volume (lots)</Label>
                  <Input
                    className="h-8 text-xs"
                    value={volume}
                    onChange={(e) => setVolume(e.target.value)}
                  />
                </div>
              ) : (
                <div className="space-y-1">
                  <Label className="text-xs">Risk per Trade (%)</Label>
                  <Input
                    className="h-8 text-xs"
                    type="number"
                    value={riskPct}
                    onChange={(e) => setRiskPct(e.target.value)}
                    placeholder="e.g. 1 = 1%"
                  />
                </div>
              )}
              <div className="space-y-1">
                <Label className="text-xs">Spread (pips)</Label>
                <Input
                  className="h-8 text-xs"
                  value={spread}
                  onChange={(e) => setSpread(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Commission/lot ($)</Label>
                <Input
                  className="h-8 text-xs"
                  value={commissionPerLot}
                  onChange={(e) => setCommissionPerLot(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">TP Partial Close Ratio</Label>
                <Input
                  className="h-8 text-xs"
                  value={tpPartialCloseRatio}
                  onChange={(e) => setTpPartialCloseRatio(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Parallel Workers</Label>
                <Select value={maxWorkers} onValueChange={setMaxWorkers}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[1, 2, 4, 6, 8, 12, 16].map((n) => (
                      <SelectItem key={n} value={String(n)} className="text-xs">
                        {n} worker{n > 1 ? "s" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Execution Mode</Label>
                <Select
                  value={mode}
                  onValueChange={(v) =>
                    setMode(v as "close_price" | "intra_candle")
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="close_price" className="text-xs">
                      Close Price
                    </SelectItem>
                    <SelectItem value="intra_candle" className="text-xs">
                      Intra-Candle
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </section>

          {/* ── CSV ── */}
          <section className="space-y-3">
            <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
              OHLCV Data
            </h2>
            <div className="space-y-1">
              <Label className="text-xs">Primary TF CSV (MT5 export)</Label>
              <Input
                type="file"
                accept=".csv"
                className="h-8 text-xs"
                onChange={async (e) => {
                  const file = e.target.files?.[0] ?? null;
                  setCsvFile(file);
                  if (file) {
                    const dates = await parseMt5CsvDates(file);
                    if (dates) {
                      setStartDate(dates.startDate);
                      setEndDate(dates.endDate);
                    }
                  }
                }}
              />
            </div>
            {contextTfs.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">
                  Context TF CSVs — required for this strategy
                </p>
                {contextTfs.map((tf) => (
                  <div key={tf} className="space-y-1">
                    <Label className="text-xs">{tf} CSV (MT5 export)</Label>
                    <Input
                      type="file"
                      accept=".csv"
                      className="h-8 text-xs"
                      onChange={(e) => {
                        const file = e.target.files?.[0] ?? null;
                        setContextCsvFiles((prev) => ({ ...prev, [tf]: file }));
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* ── Parameter Sweep Builder ── */}
          {sweepRows.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
                Parameter Sweep
              </h2>
              <div className="space-y-3">
                {sweepRows.map((row, idx) => (
                  <div
                    key={row.name}
                    className="border rounded-lg p-3 space-y-2"
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id={`enable-${row.name}`}
                        checked={row.enabled}
                        onChange={(e) =>
                          updateRow(idx, { enabled: e.target.checked })
                        }
                        className="rounded"
                      />
                      <label
                        htmlFor={`enable-${row.name}`}
                        className="text-sm font-medium cursor-pointer"
                      >
                        {row.label}
                      </label>
                      {row.enabled && (
                        <div className="ml-auto flex gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant={
                              row.mode === "range" ? "default" : "outline"
                            }
                            className="h-6 text-xs px-2"
                            onClick={() => updateRow(idx, { mode: "range" })}
                          >
                            Range
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={
                              row.mode === "list" ? "default" : "outline"
                            }
                            className="h-6 text-xs px-2"
                            onClick={() => updateRow(idx, { mode: "list" })}
                          >
                            Values
                          </Button>
                        </div>
                      )}
                    </div>

                    {row.enabled && row.mode === "range" && (
                      <div className="grid grid-cols-3 gap-2">
                        <div className="space-y-1">
                          <Label className="text-xs">Min</Label>
                          <Input
                            className="h-7 text-xs"
                            value={row.min}
                            onChange={(e) =>
                              updateRow(idx, { min: e.target.value })
                            }
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Max</Label>
                          <Input
                            className="h-7 text-xs"
                            value={row.max}
                            onChange={(e) =>
                              updateRow(idx, { max: e.target.value })
                            }
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Step</Label>
                          <Input
                            className="h-7 text-xs"
                            value={row.step}
                            onChange={(e) =>
                              updateRow(idx, { step: e.target.value })
                            }
                          />
                        </div>
                      </div>
                    )}

                    {row.enabled && row.mode === "list" && (
                      <div className="space-y-1">
                        <Label className="text-xs">
                          Values (comma-separated)
                        </Label>
                        <Input
                          className="h-7 text-xs"
                          placeholder="e.g. 2, 3, 5, 8"
                          value={row.list}
                          onChange={(e) =>
                            updateRow(idx, { list: e.target.value })
                          }
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="text-xs text-muted-foreground">
                Total combinations:{" "}
                <span
                  className={
                    computedCombinations > 100000
                      ? "text-destructive font-bold"
                      : "font-medium"
                  }
                >
                  {computedCombinations}
                </span>
                {computedCombinations > 100000 && " — reduce ranges (max 100000)"}
              </div>
            </section>
          )}

          {registryParams.length === 0 && strategyId && (
            <p className="text-xs text-muted-foreground">
              This strategy has no optimizable numeric parameters registered.
            </p>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}

          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => router.back()}
            >
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting
                ? "Submitting…"
                : `Run Optimization (${computedCombinations} combos)`}
            </Button>
          </div>
        </form>
      </div>
    </SidebarInset>
  );
}
