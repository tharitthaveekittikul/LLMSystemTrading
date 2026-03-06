"use client";

import { useCallback, useEffect, useState } from "react";
import { formatDateTime } from "@/lib/date";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { accountsApi } from "@/lib/api/accounts";
import { signalsApi } from "@/lib/api";
import type { Account, AISignal, AnalyzeResult } from "@/types/trading";

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

function actionVariant(a: string): "default" | "destructive" | "secondary" {
  if (a === "BUY") return "default";
  if (a === "SELL") return "destructive";
  return "secondary";
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 max-w-48 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground w-8 text-right">
        {pct}%
      </span>
    </div>
  );
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<AISignal[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(
    null,
  );

  // Analyze form state
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("M15");

  // Market Watch symbol selector
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbolsLoading, setSymbolsLoading] = useState(false);

  useEffect(() => {
    if (!selectedAccountId) {
      setSymbols([]);
      return;
    }
    (async () => {
      setSymbolsLoading(true);
      try {
        const data = await accountsApi.getSymbols(Number(selectedAccountId));
        setSymbols(data);
        setSymbol(""); // reset so no stale text carries over
      } catch {
        setSymbols([]);
      } finally {
        setSymbolsLoading(false);
      }
    })();
  }, [selectedAccountId]);

  const loadSignals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await signalsApi.list({ limit: 50 });
      setSignals(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load signals");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSignals();
    (async () => {
      try {
        const data = await accountsApi.list();
        setAccounts(data);
      } catch {
        // silently ignore — accounts list is optional for signal display
      }
    })();
  }, [loadSignals]);

  async function handleAnalyze() {
    if (!selectedAccountId) return;
    setAnalyzing(true);
    setError(null);
    setAnalyzeResult(null);
    try {
      const result = await signalsApi.analyze(Number(selectedAccountId), {
        symbol,
        timeframe,
      });
      setAnalyzeResult(result);
      await loadSignals();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <SidebarInset>
      <AppHeader title="AI Signals" showAccountSelector={false} showConnectionStatus={false} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {/* Trigger form */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Run Analysis</CardTitle>
            <CardDescription>
              Select an account and symbol to trigger a live LLM market
              analysis.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_120px_auto] gap-4 items-end">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-medium text-muted-foreground">
                  Account
                </Label>
                <Select
                  value={selectedAccountId}
                  onValueChange={setSelectedAccountId}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select account" />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {a.name} ({a.broker})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-medium text-muted-foreground">
                  Symbol
                </Label>
                <Select
                  value={symbol}
                  onValueChange={setSymbol}
                  disabled={symbolsLoading || symbols.length === 0}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue
                      placeholder={
                        symbolsLoading ? "Loading…" : "Select symbol"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {symbols.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-medium text-muted-foreground">
                  Timeframe
                </Label>
                <Select value={timeframe} onValueChange={setTimeframe}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIMEFRAMES.map((tf) => (
                      <SelectItem key={tf} value={tf}>
                        {tf}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={handleAnalyze}
                disabled={analyzing || !selectedAccountId}
                className="w-full sm:w-auto"
              >
                {analyzing ? "Analyzing…" : "Analyze"}
              </Button>
            </div>

            {analyzeResult && (
              <div className="mt-4 p-4 rounded-lg bg-muted/60 border text-sm space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant={actionVariant(analyzeResult.action)}>
                    {analyzeResult.action}
                  </Badge>
                  <span className="text-muted-foreground">
                    confidence {Math.round(analyzeResult.confidence * 100)}%
                  </span>
                  {analyzeResult.order_placed && (
                    <Badge
                      variant="outline"
                      className="text-green-600 border-green-500"
                    >
                      ✓ Order placed #{analyzeResult.ticket}
                    </Badge>
                  )}
                </div>
                <p className="text-muted-foreground leading-relaxed">
                  {analyzeResult.rationale}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Signal feed */}
        <div className="space-y-2">
          {signals.length === 0 && !loading && (
            <p className="text-center text-muted-foreground py-8 text-sm">
              No signals yet — run an analysis above.
            </p>
          )}
          {signals.map((s) => (
            <Card key={s.id} className="overflow-hidden">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant={actionVariant(s.signal)}>{s.signal}</Badge>
                    <span className="font-medium">{s.symbol}</span>
                    <Badge variant="outline" className="text-xs">
                      {s.timeframe}
                    </Badge>
                    {s.trade_id && (
                      <Badge
                        variant="outline"
                        className="text-xs text-green-600 border-green-500"
                      >
                        Executed
                      </Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {formatDateTime(s.created_at)}
                  </span>
                </div>
                <div className="mt-3">
                  <ConfidenceBar value={s.confidence} />
                </div>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {s.rationale}
                </p>
                <p className="mt-1 text-xs text-muted-foreground/70">
                  {s.llm_provider} / {s.model_name || "default"}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </SidebarInset>
  );
}
