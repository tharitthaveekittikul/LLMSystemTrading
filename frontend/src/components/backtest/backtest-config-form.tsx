"use client";

import { useState } from "react";
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
import { backtestApi } from "@/lib/api";
import type { BacktestRunRequest, BacktestRunSummary } from "@/types/trading";

interface Strategy {
  id: number;
  name: string;
  timeframe: string;
  strategy_type: string;
  primary_tf: string;
  context_tfs: string[];
}

interface Props {
  strategies: Strategy[];
  onRunCreated: (run: BacktestRunSummary) => void;
}



export function BacktestConfigForm({ strategies, onRunCreated }: Props) {
  const [strategyId, setStrategyId] = useState<string>("");
  const [symbol, setSymbol] = useState("XAUUSD.s");
  const [startDate, setStartDate] = useState("2017-01-02");
  const [endDate, setEndDate] = useState("2023-12-29");
  const [balance, setBalance] = useState("1000");
  const [spread, setSpread] = useState("1.5");
  const [mode, setMode] = useState<"close_price" | "intra_candle">(
    "close_price",
  );
  const [maxLlm, setMaxLlm] = useState("10");
  const [volume, setVolume] = useState("0.01");
  const [sizingMode, setSizingMode] = useState<"fixed" | "risk_pct">("fixed");
  const [riskPct, setRiskPct] = useState("1");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvAvgSpread, setCsvAvgSpread] = useState<number | null>(null);
  const [contextCsvFiles, setContextCsvFiles] = useState<Record<string, File | null>>({});

  const selectedStrategy = strategies.find((s) => String(s.id) === strategyId);
  // Exclude primary TF from context list (it's already the main CSV)
  const contextTfs = (selectedStrategy?.context_tfs ?? []).filter(
    (tf) => tf !== selectedStrategy?.primary_tf,
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!strategyId) {
      setError("Please select a strategy");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      let csvUploadId: string | undefined;
      if (csvFile) {
        const result = await backtestApi.uploadCsv(csvFile);
        csvUploadId = result.upload_id;
        setCsvAvgSpread(result.avg_spread_pts ?? null);
      }

      // Upload context TF CSVs if provided
      let csvUploads: Record<string, string> | undefined;
      const ctxEntries = Object.entries(contextCsvFiles).filter(([, f]) => f != null);
      if (ctxEntries.length > 0) {
        csvUploads = {};
        for (const [tf, file] of ctxEntries) {
          if (file) {
            const r = await backtestApi.uploadCsv(file);
            csvUploads[tf] = r.upload_id;
          }
        }
      }

      const req: BacktestRunRequest = {
        strategy_id: Number(strategyId),
        symbol,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        initial_balance: Number(balance),
        spread_pips: Number(spread),
        execution_mode: mode,
        max_llm_calls: Number(maxLlm),
        volume: Number(volume),
        risk_pct: sizingMode === "risk_pct" ? Number(riskPct) / 100 : undefined,
        csv_upload_id: csvUploadId,
        csv_uploads: csvUploads,
      };
      const run = await backtestApi.submitRun(req);
      onRunCreated(run);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="space-y-1">
        <Label className="text-xs">Strategy</Label>
        <Select value={strategyId} onValueChange={setStrategyId}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select strategy" />
          </SelectTrigger>
          <SelectContent>
            {strategies.map((s) => (
              <SelectItem key={s.id} value={String(s.id)} className="text-xs">
                {s.name} ({s.timeframe})
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

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">Start Date</Label>
          <Input
            className="h-8 text-xs"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">End Date</Label>
          <Input
            className="h-8 text-xs"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">Balance ($)</Label>
          <Input
            className="h-8 text-xs"
            type="number"
            value={balance}
            onChange={(e) => setBalance(e.target.value)}
          />
        </div>
        {!csvFile ? (
          <div className="space-y-1">
            <Label className="text-xs">Spread (pips)</Label>
            <Input
              className="h-8 text-xs"
              type="number"
              step="0.1"
              value={spread}
              onChange={(e) => setSpread(e.target.value)}
            />
          </div>
        ) : csvAvgSpread != null ? (
          <p className="text-[10px] text-muted-foreground">
            Avg spread from CSV: ~{csvAvgSpread} pts (applied per candle)
          </p>
        ) : null}
      </div>

      <div className="space-y-1">
        <Label className="text-xs">Execution Mode</Label>
        <Select
          value={mode}
          onValueChange={(v) => setMode(v as "close_price" | "intra_candle")}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="close_price" className="text-xs">
              Close Price
            </SelectItem>
            <SelectItem value="intra_candle" className="text-xs">
              Intra-Candle + Spread
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">LLM Max Calls</Label>
          <Input
            className="h-8 text-xs"
            type="number"
            value={maxLlm}
            onChange={(e) => setMaxLlm(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Lot Sizing</Label>
          <Select
            value={sizingMode}
            onValueChange={(v) => setSizingMode(v as "fixed" | "risk_pct")}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fixed" className="text-xs">Fixed Lot</SelectItem>
              <SelectItem value="risk_pct" className="text-xs">% Risk / Trade</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {sizingMode === "fixed" ? (
        <div className="space-y-1">
          <Label className="text-xs">Volume (lots)</Label>
          <Input
            className="h-8 text-xs"
            type="number"
            step="0.01"
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
            step="0.1"
            min="0.1"
            max="100"
            value={riskPct}
            onChange={(e) => setRiskPct(e.target.value)}
          />
          <p className="text-[10px] text-muted-foreground">
            Lot size auto-calculated to risk this % of current balance per trade
          </p>
        </div>
      )}

      <div className="space-y-1">
        <Label className="text-xs">
          {selectedStrategy ? `${selectedStrategy.primary_tf} CSV` : "CSV Data"}{" "}
          <span className="text-muted-foreground">(optional — overrides MT5)</span>
        </Label>
        <Input
          className="h-8 text-xs cursor-pointer"
          type="file"
          accept=".csv"
          onChange={(e) => {
            setCsvFile(e.target.files?.[0] ?? null);
            setCsvAvgSpread(null);
          }}
        />
        <p className="text-[10px] text-muted-foreground">
          MT5 export format: tab-separated with &lt;DATE&gt; &lt;TIME&gt;
          &lt;OPEN&gt;…&lt;SPREAD&gt; headers
        </p>
      </div>

      {contextTfs.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
            Context TF CSVs (for MTF analysis)
          </p>
          {contextTfs.map((tf) => (
            <div key={tf} className="space-y-1">
              <Label className="text-xs">{tf} CSV <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                className="h-8 text-xs cursor-pointer"
                type="file"
                accept=".csv"
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null;
                  setContextCsvFiles((prev) => ({ ...prev, [tf]: file }));
                }}
              />
            </div>
          ))}
        </div>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}

      <Button
        type="submit"
        className="w-full h-8 text-xs"
        disabled={submitting}
      >
        {submitting ? "Submitting…" : "Run Backtest"}
      </Button>
    </form>
  );
}
