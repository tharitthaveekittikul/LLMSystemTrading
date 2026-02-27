"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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

function actionVariant(
  a: string,
): "default" | "destructive" | "secondary" {
  if (a === "BUY") return "default";
  if (a === "SELL") return "destructive";
  return "secondary";
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80
      ? "bg-green-500"
      : pct >= 60
        ? "bg-yellow-500"
        : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground">{pct}%</span>
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
    accountsApi.list().then(setAccounts).catch(() => {});
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
      <AppHeader title="AI Signals" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {/* Trigger form */}
        <Card>
          <CardHeader className="pb-2 text-sm font-medium">
            Run Analysis
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Account</Label>
                <Select
                  value={selectedAccountId}
                  onValueChange={setSelectedAccountId}
                >
                  <SelectTrigger className="w-44">
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
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Symbol</Label>
                <Input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  className="w-28 text-sm"
                  placeholder="EURUSD"
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Timeframe</Label>
                <Select value={timeframe} onValueChange={setTimeframe}>
                  <SelectTrigger className="w-24">
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
              >
                {analyzing ? "Analyzing…" : "Analyze"}
              </Button>
            </div>

            {analyzeResult && (
              <div className="mt-3 p-3 rounded-md bg-muted text-sm space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant={actionVariant(analyzeResult.action)}>
                    {analyzeResult.action}
                  </Badge>
                  <span className="text-muted-foreground">
                    confidence {Math.round(analyzeResult.confidence * 100)}%
                  </span>
                  {analyzeResult.order_placed && (
                    <Badge variant="outline" className="text-green-600">
                      Order placed #{analyzeResult.ticket}
                    </Badge>
                  )}
                </div>
                <p className="text-muted-foreground">{analyzeResult.rationale}</p>
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
                      <Badge variant="outline" className="text-xs text-green-600">
                        Executed
                      </Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {new Date(s.created_at).toLocaleString()}
                  </span>
                </div>
                <div className="mt-2">
                  <ConfidenceBar value={s.confidence} />
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {s.rationale}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
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
