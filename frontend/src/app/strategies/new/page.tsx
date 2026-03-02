"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { strategiesApi } from "@/lib/api/strategies";
import { accountsApi } from "@/lib/api/accounts";
import type { Account, CreateStrategyPayload } from "@/types/trading";
import { X } from "lucide-react";

const STEP_LABELS = [
  "Basics",
  "Market & Schedule",
  "Configuration",
  "Bind Accounts",
];
const TIMEFRAMES = ["M15", "M30", "H1", "H4", "D1"];
type StratType = "config" | "prompt" | "code";
type TrigType = "candle_close" | "interval";

export default function NewStrategyPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<number[]>([]);
  const [form, setForm] = useState<CreateStrategyPayload>({
    name: "",
    strategy_type: "config",
    trigger_type: "candle_close",
    symbols: [],
    timeframe: "M15",
    news_filter: true,
  });

  useEffect(() => {
    (async () => {
      try {
        const data = await accountsApi.list();
        setAccounts(data);
      } catch (err) {
        console.error(err);
      }
    })();
  }, []);

  function addSymbol() {
    const sym = symbolInput.trim();
    if (sym && !form.symbols.includes(sym)) {
      setForm((f) => ({ ...f, symbols: [...f.symbols, sym] }));
    }
    setSymbolInput("");
  }

  function removeSymbol(sym: string) {
    setForm((f) => ({ ...f, symbols: f.symbols.filter((s) => s !== sym) }));
  }

  async function handleSubmit() {
    setSubmitting(true);
    try {
      const strategy = await strategiesApi.create(form);
      await Promise.all(
        selectedAccounts.map((aid) => strategiesApi.bind(strategy.id, aid)),
      );
      router.push("/strategies");
    } catch (err) {
      console.error(err);
      setSubmitting(false);
    }
  }

  const canNext =
    step === 0
      ? form.name.trim().length > 0
      : step === 1
        ? form.symbols.length > 0
        : true;

  return (
    <SidebarInset>
      <AppHeader title="New Strategy" />
      <div className="flex flex-1 flex-col gap-6 p-4 max-w-2xl mx-auto w-full">
        {/* Step indicator */}
        <div className="flex gap-1">
          {STEP_LABELS.map((label, i) => (
            <div key={i} className="flex-1 flex flex-col gap-1">
              <div
                className={`h-1 rounded-full ${i <= step ? "bg-primary" : "bg-muted"}`}
              />
              <span className="text-xs text-muted-foreground hidden sm:block">
                {label}
              </span>
            </div>
          ))}
        </div>

        <div className="rounded-lg border p-6 space-y-6">
          {/* Step 0: Basics */}
          {step === 0 && (
            <>
              <h3 className="font-semibold">Step 1 — Basics</h3>
              <div className="space-y-2">
                <Label htmlFor="name">Name *</Label>
                <Input
                  id="name"
                  value={form.name}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, name: e.target.value }))
                  }
                  placeholder="e.g. EURUSD Scalp M15"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={form.description ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      description: e.target.value || undefined,
                    }))
                  }
                  placeholder="Optional description"
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <Label>Type</Label>
                <div className="flex gap-2">
                  {(["config", "prompt", "code"] as StratType[]).map((t) => (
                    <button
                      key={t}
                      onClick={() =>
                        setForm((f) => ({ ...f, strategy_type: t }))
                      }
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium capitalize transition-colors ${form.strategy_type === t ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted"}`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {form.strategy_type === "config"
                    ? "Simple risk parameters — lot size, SL, TP."
                    : form.strategy_type === "prompt"
                      ? "Custom LLM system prompt for market analysis."
                      : "Python class extending BaseStrategy in backend/strategies/."}
                </p>
              </div>
            </>
          )}

          {/* Step 1: Market & Schedule */}
          {step === 1 && (
            <>
              <h3 className="font-semibold">Step 2 — Market & Schedule</h3>
              <div className="space-y-2">
                <Label>Symbols *</Label>
                <div className="flex gap-2">
                  <Input
                    value={symbolInput}
                    onChange={(e) => setSymbolInput(e.target.value)}
                    onKeyDown={(e) =>
                      e.key === "Enter" && (e.preventDefault(), addSymbol())
                    }
                    placeholder="e.g. EURUSD"
                  />
                  <Button type="button" onClick={addSymbol} variant="outline">
                    Add
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {form.symbols.map((sym) => (
                    <Badge key={sym} variant="secondary" className="gap-1">
                      {sym}
                      <button onClick={() => removeSymbol(sym)}>
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Timeframe</Label>
                <div className="flex gap-2">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      onClick={() => setForm((f) => ({ ...f, timeframe: tf }))}
                      className={`flex-1 rounded-lg border px-2 py-2 text-sm font-medium transition-colors ${form.timeframe === tf ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted"}`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Trigger</Label>
                <div className="flex gap-2">
                  {(["candle_close", "interval"] as TrigType[]).map((t) => (
                    <button
                      key={t}
                      onClick={() =>
                        setForm((f) => ({ ...f, trigger_type: t }))
                      }
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${form.trigger_type === t ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted"}`}
                    >
                      {t === "candle_close" ? "Candle close" : "Fixed interval"}
                    </button>
                  ))}
                </div>
                {form.trigger_type === "interval" && (
                  <div className="flex items-center gap-2 mt-2">
                    <Input
                      type="number"
                      min={1}
                      value={form.interval_minutes ?? 15}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          interval_minutes: Number(e.target.value),
                        }))
                      }
                      className="w-24"
                    />
                    <span className="text-sm text-muted-foreground">
                      minutes
                    </span>
                  </div>
                )}
              </div>
            </>
          )}

          {/* Step 2: Configuration (type-specific) */}
          {step === 2 && (
            <>
              <h3 className="font-semibold">Step 3 — Configuration</h3>
              {form.strategy_type === "config" && (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                      <Label>Lot size</Label>
                      <Input
                        type="number"
                        step="0.01"
                        placeholder="default"
                        value={form.lot_size ?? ""}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            lot_size: e.target.value
                              ? Number(e.target.value)
                              : undefined,
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <Label>SL pips</Label>
                      <Input
                        type="number"
                        placeholder="default"
                        value={form.sl_pips ?? ""}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            sl_pips: e.target.value
                              ? Number(e.target.value)
                              : undefined,
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <Label>TP pips</Label>
                      <Input
                        type="number"
                        placeholder="default"
                        value={form.tp_pips ?? ""}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            tp_pips: e.target.value
                              ? Number(e.target.value)
                              : undefined,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Switch
                      checked={form.news_filter ?? true}
                      onCheckedChange={(v) =>
                        setForm((f) => ({ ...f, news_filter: v }))
                      }
                      id="news_filter"
                    />
                    <Label htmlFor="news_filter">
                      News filter (skip trading near high-impact news)
                    </Label>
                  </div>
                </div>
              )}
              {form.strategy_type === "prompt" && (
                <div className="space-y-2">
                  <Label>Custom LLM system prompt</Label>
                  <Textarea
                    value={form.custom_prompt ?? ""}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        custom_prompt: e.target.value || undefined,
                      }))
                    }
                    className="font-mono text-sm"
                    rows={10}
                    placeholder="You are a forex trading expert specializing in..."
                  />
                </div>
              )}
              {form.strategy_type === "code" && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Module path</Label>
                    <Input
                      value={form.module_path ?? ""}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          module_path: e.target.value || undefined,
                        }))
                      }
                      placeholder="strategies.eurusd_m15_scalp"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Class name</Label>
                    <Input
                      value={form.class_name ?? ""}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          class_name: e.target.value || undefined,
                        }))
                      }
                      placeholder="EURUSDScalp"
                    />
                  </div>
                  <div className="rounded-lg bg-muted p-4 text-sm text-muted-foreground space-y-2">
                    <p className="font-medium text-foreground">
                      How to add a code strategy:
                    </p>
                    <ol className="list-decimal list-inside space-y-1">
                      <li>
                        Create{" "}
                        <code className="font-mono">
                          backend/strategies/your_strategy.py
                        </code>
                      </li>
                      <li>
                        Extend <code className="font-mono">BaseStrategy</code>{" "}
                        and implement{" "}
                        <code className="font-mono">system_prompt()</code>
                      </li>
                      <li>Restart the backend once</li>
                      <li>Enter module path and class name above</li>
                    </ol>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Step 3: Bind Accounts */}
          {step === 3 && (
            <>
              <h3 className="font-semibold">Step 4 — Bind Accounts</h3>
              <p className="text-sm text-muted-foreground">
                Select which accounts will run this strategy.
              </p>
              <div className="space-y-2">
                {accounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No accounts found.{" "}
                    <Link href="/accounts" className="underline">
                      Add an account
                    </Link>{" "}
                    first.
                  </p>
                ) : (
                  accounts.map((acc) => (
                    <div
                      key={acc.id}
                      className="flex items-center gap-3 rounded-lg border p-3"
                    >
                      <Checkbox
                        id={`acc-${acc.id}`}
                        checked={selectedAccounts.includes(acc.id)}
                        onCheckedChange={(checked) =>
                          setSelectedAccounts((prev) =>
                            checked
                              ? [...prev, acc.id]
                              : prev.filter((id) => id !== acc.id),
                          )
                        }
                      />
                      <Label
                        htmlFor={`acc-${acc.id}`}
                        className="flex-1 cursor-pointer"
                      >
                        <span className="font-medium">{acc.name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">
                          #{acc.login}
                        </span>
                      </Label>
                      <Badge
                        variant={acc.is_live ? "destructive" : "secondary"}
                        className="text-xs"
                      >
                        {acc.is_live ? "Live" : "Paper"}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>

        {/* Navigation */}
        <div className="flex justify-between">
          <div>
            {step === 0 ? (
              <Button variant="outline" asChild>
                <Link href="/strategies">Cancel</Link>
              </Button>
            ) : (
              <Button variant="outline" onClick={() => setStep((s) => s - 1)}>
                Back
              </Button>
            )}
          </div>
          <div>
            {step < 3 ? (
              <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext}>
                Next
              </Button>
            ) : (
              <Button
                onClick={handleSubmit}
                disabled={
                  submitting || !form.name.trim() || form.symbols.length === 0
                }
              >
                {submitting ? "Creating..." : "Create Strategy"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </SidebarInset>
  );
}
