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
}

interface Props {
  strategies: Strategy[];
  onRunCreated: (run: BacktestRunSummary) => void;
}

const sixYearsAgo = () => {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 6);
  return d.toISOString().slice(0, 10);
};

export function BacktestConfigForm({ strategies, onRunCreated }: Props) {
  const [strategyId, setStrategyId] = useState<string>("");
  const [symbol, setSymbol] = useState("EURUSD");
  const [startDate, setStartDate] = useState(sixYearsAgo());
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [balance, setBalance] = useState("10000");
  const [spread, setSpread] = useState("1.5");
  const [mode, setMode] = useState<"close_price" | "intra_candle">(
    "close_price",
  );
  const [maxLlm, setMaxLlm] = useState("100");
  const [volume, setVolume] = useState("0.1");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvAvgSpread, setCsvAvgSpread] = useState<number | null>(null);
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
        csv_upload_id: csvUploadId,
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
          <Label className="text-xs">Volume (lots)</Label>
          <Input
            className="h-8 text-xs"
            type="number"
            step="0.01"
            value={volume}
            onChange={(e) => setVolume(e.target.value)}
          />
        </div>
      </div>

      <div className="space-y-1">
        <Label className="text-xs">CSV Data (optional — overrides MT5)</Label>
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
          MT5 export format: tab-separated with &lt;DATE&gt; &lt;TIME&gt; &lt;OPEN&gt;…&lt;SPREAD&gt; headers
        </p>
      </div>

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
