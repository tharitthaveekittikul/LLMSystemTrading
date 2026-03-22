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
import type { Account, CreateStrategyPayload, StrategyRegistryEntry } from "@/types/trading";
import { X, ChevronDown, ChevronUp } from "lucide-react";
import { SkipHoursGrid } from "../../../components/strategies/skip-hours-grid";
import { SkipWeekdaysGrid } from "../../../components/strategies/skip-weekdays-grid";
import { StrategyClassSelector } from "../../../components/strategies/strategy-class-selector";
import { StrategyParamsForm } from "../../../components/strategies/strategy-params-form";

const STEP_LABELS = ["Basics", "Market & Schedule", "Configuration", "Bind Accounts"];
const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
type ExecMode = "llm_only" | "rule_then_llm" | "rule_only" | "hybrid_validator" | "multi_agent";
type TrigType = "candle_close" | "interval";

export default function NewStrategyPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<number[]>([]);
  const [registryEntries, setRegistryEntries] = useState<StrategyRegistryEntry[]>([]);
  const [strategyParamValues, setStrategyParamValues] = useState<Record<string, unknown>>({});
  const [showCustomClass, setShowCustomClass] = useState(false);
  const [form, setForm] = useState<CreateStrategyPayload>({
    name: "",
    execution_mode: "llm_only",
    trigger_type: "candle_close",
    symbols: [],
    timeframe: "M15",
    primary_tf: "M15",
    context_tfs: [],
    news_filter: true,
    skip_hours: [],
    skip_hours_timezone: "Asia/Bangkok",
    skip_weekdays: [],
  });

  useEffect(() => {
    (async () => {
      try {
        const [accs, reg] = await Promise.all([
          accountsApi.list(),
          strategiesApi.registry(),
        ]);
        setAccounts(accs);
        setRegistryEntries(reg);
      } catch (err) {
        console.error(err);
      }
    })();
  }, []);

  function selectRegistryEntry(key: string) {
    const entry = registryEntries.find((e) => e.key === key);
    if (!entry) return;
    // Pre-fill default param values from the schema
    const defaults: Record<string, unknown> = {};
    for (const p of entry.params) defaults[p.name] = p.default;
    setStrategyParamValues(defaults);
    setForm((f) => ({
      ...f,
      strategy_key: key,
      execution_mode: entry.execution_mode as ExecMode,
      module_path: undefined,
      class_name: undefined,
    }));
    setShowCustomClass(false);
  }

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
      const payload: CreateStrategyPayload = {
        ...form,
        strategy_params: Object.keys(strategyParamValues).length > 0 ? strategyParamValues : undefined,
      };
      const strategy = await strategiesApi.create(payload);
      await Promise.all(selectedAccounts.map((aid) => strategiesApi.bind(strategy.id, aid)));
      router.push("/strategies");
    } catch (err) {
      console.error(err);
      setSubmitting(false);
    }
  }

  const selectedEntry = registryEntries.find((e) => e.key === form.strategy_key) ?? null;

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
              <div className={`h-1 rounded-full ${i <= step ? "bg-primary" : "bg-muted"}`} />
              <span className="text-xs text-muted-foreground hidden sm:block">{label}</span>
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
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. EURUSD Scalp M15"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={form.description ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, description: e.target.value || undefined }))
                  }
                  placeholder="Optional description"
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <Label>Execution Mode</Label>
                <div className="grid grid-cols-1 gap-2">
                  {(
                    [
                      ["llm_only", "LLM Only", "LLM analyzes every candle. Requires custom_prompt."],
                      ["rule_then_llm", "Rule → LLM", "Rule pre-filters; LLM validates triggered signals. Requires Python class."],
                      ["rule_only", "Rule Only", "Fully deterministic rules. Zero LLM cost. Requires Python class."],
                      ["hybrid_validator", "Hybrid Validator", "Rules open the trade; LLM validates post-entry. Requires Python class."],
                      ["multi_agent", "Multi-Agent", "Rules + LLM run in parallel; consensus required. Requires Python class."],
                    ] as [ExecMode, string, string][]
                  ).map(([mode, label, desc]) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() =>
                        setForm((f) => ({
                          ...f,
                          execution_mode: mode,
                          // Clear registry selection if switching away from its mode
                          ...(f.strategy_key &&
                            registryEntries.find((e) => e.key === f.strategy_key)?.execution_mode !== mode
                            ? { strategy_key: undefined }
                            : {}),
                        }))
                      }
                      className={`text-left rounded-lg border px-3 py-2 transition-colors ${
                        form.execution_mode === mode
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      <p className="text-sm font-medium">{label}</p>
                      <p className={`text-xs mt-0.5 ${form.execution_mode === mode ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
                        {desc}
                      </p>
                    </button>
                  ))}
                </div>
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
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addSymbol())}
                    placeholder="e.g. EURUSD"
                  />
                  <Button type="button" onClick={addSymbol} variant="outline">Add</Button>
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
                <div className="flex gap-2 flex-wrap">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, timeframe: tf }))}
                      className={`rounded-lg border px-2 py-2 text-sm font-medium transition-colors ${form.timeframe === tf ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted"}`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>
                  Primary TF{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (main trading timeframe for MTF strategies)
                  </span>
                </Label>
                <div className="flex gap-2 flex-wrap">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() =>
                        setForm((f) => ({
                          ...f,
                          primary_tf: tf,
                          context_tfs: (f.context_tfs ?? []).filter((t) => t !== tf),
                        }))
                      }
                      className={`rounded-lg border px-2 py-2 text-sm font-medium transition-colors ${
                        form.primary_tf === tf
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>
                  Context TFs{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (optional — additional timeframes for MTF analysis)
                  </span>
                </Label>
                <div className="flex gap-2 flex-wrap">
                  {TIMEFRAMES.filter((tf) => tf !== form.primary_tf).map((tf) => {
                    const selected = (form.context_tfs ?? []).includes(tf);
                    return (
                      <button
                        key={tf}
                        type="button"
                        onClick={() =>
                          setForm((f) => {
                            const cur = f.context_tfs ?? [];
                            return {
                              ...f,
                              context_tfs: selected ? cur.filter((t) => t !== tf) : [...cur, tf],
                            };
                          })
                        }
                        className={`rounded-lg border-2 px-2 py-2 text-sm font-medium transition-colors ${
                          selected
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border bg-background hover:bg-muted"
                        }`}
                      >
                        {tf}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Trigger</Label>
                <div className="flex gap-2">
                  {(["candle_close", "interval"] as TrigType[]).map((t) => (
                    <button
                      key={t}
                      onClick={() => setForm((f) => ({ ...f, trigger_type: t }))}
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
                        setForm((f) => ({ ...f, interval_minutes: Number(e.target.value) }))
                      }
                      className="w-24"
                    />
                    <span className="text-sm text-muted-foreground">minutes</span>
                  </div>
                )}
              </div>
              <div className="space-y-2">
                <Label>
                  Skip Hours{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (candle closes at these hours will be ignored)
                  </span>
                </Label>
                <SkipHoursGrid
                  hours={form.skip_hours ?? []}
                  timezone={form.skip_hours_timezone ?? "Asia/Bangkok"}
                  onChange={(h, tz) =>
                    setForm((f) => ({ ...f, skip_hours: h, skip_hours_timezone: tz }))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>
                  Skip Days{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (strategy will not run on these days of the week)
                  </span>
                </Label>
                <SkipWeekdaysGrid
                  days={form.skip_weekdays ?? []}
                  onChange={(d) => setForm((f) => ({ ...f, skip_weekdays: d }))}
                />
              </div>
            </>
          )}

          {/* Step 2: Configuration */}
          {step === 2 && (
            <>
              <h3 className="font-semibold">Step 3 — Configuration</h3>

              {/* LLM Only: custom prompt */}
              {form.execution_mode === "llm_only" && (
                <div className="space-y-2">
                  <Label>Custom LLM System Prompt</Label>
                  <Textarea
                    value={form.custom_prompt ?? ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, custom_prompt: e.target.value || undefined }))
                    }
                    className="font-mono text-sm"
                    rows={10}
                    placeholder="You are a forex trading expert specializing in..."
                  />
                </div>
              )}

              {/* Rule-based modes: registry selector + params */}
              {form.execution_mode !== "llm_only" && (
                <div className="space-y-5">
                  {/* Registry selector */}
                  <div className="space-y-2">
                    <Label>Strategy Class</Label>
                    <p className="text-xs text-muted-foreground">
                      Select a registered strategy. Parameters will appear below.
                    </p>
                    <StrategyClassSelector
                      entries={registryEntries.filter(
                        (e) => e.execution_mode === form.execution_mode
                      )}
                      value={form.strategy_key ?? null}
                      onChange={selectRegistryEntry}
                    />
                    {registryEntries.filter((e) => e.execution_mode === form.execution_mode).length === 0 && (
                      <p className="text-xs text-muted-foreground mt-1">
                        No registered strategies for this execution mode yet.
                      </p>
                    )}
                  </div>

                  {/* Dynamic params for selected strategy */}
                  {selectedEntry && selectedEntry.params.length > 0 && (
                    <div className="space-y-3 rounded-lg border p-4">
                      <p className="text-sm font-medium">
                        {selectedEntry.display_name} — Parameters
                      </p>
                      <StrategyParamsForm
                        params={selectedEntry.params}
                        values={strategyParamValues}
                        onChange={setStrategyParamValues}
                      />
                    </div>
                  )}

                  {/* Divider + custom class fallback */}
                  <div className="border-t pt-4">
                    <button
                      type="button"
                      onClick={() => setShowCustomClass((v) => !v)}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showCustomClass ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      Use a custom (unregistered) class instead
                    </button>
                    {showCustomClass && (
                      <div className="mt-3 space-y-3">
                        <div className="space-y-1.5">
                          <Label>Module Path</Label>
                          <Input
                            value={form.module_path ?? ""}
                            onChange={(e) =>
                              setForm((f) => ({
                                ...f,
                                module_path: e.target.value || undefined,
                                strategy_key: undefined,
                              }))
                            }
                            placeholder="strategies.harmonic.harmonic_strategy"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label>Class Name</Label>
                          <Input
                            value={form.class_name ?? ""}
                            onChange={(e) =>
                              setForm((f) => ({
                                ...f,
                                class_name: e.target.value || undefined,
                                strategy_key: undefined,
                              }))
                            }
                            placeholder="HarmonicStrategy"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Shared: Risk sizing */}
              <div className="space-y-3 rounded-lg border p-4">
                <p className="text-sm font-medium">Risk Sizing (optional)</p>
                <div className="grid grid-cols-3 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Lot Size</Label>
                    <Input
                      type="number"
                      step="0.01"
                      min={0.01}
                      value={form.lot_size ?? ""}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          lot_size: e.target.value ? Number(e.target.value) : undefined,
                        }))
                      }
                      placeholder="0.10"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">SL (pips)</Label>
                    <Input
                      type="number"
                      step="1"
                      min={0}
                      value={form.sl_pips ?? ""}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          sl_pips: e.target.value ? Number(e.target.value) : undefined,
                        }))
                      }
                      placeholder="20"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">TP (pips)</Label>
                    <Input
                      type="number"
                      step="1"
                      min={0}
                      value={form.tp_pips ?? ""}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          tp_pips: e.target.value ? Number(e.target.value) : undefined,
                        }))
                      }
                      placeholder="40"
                    />
                  </div>
                </div>
              </div>

              {/* News filter */}
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium cursor-pointer" htmlFor="news-filter">
                    News Filter
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    Pause trading around high-impact news events
                  </p>
                </div>
                <Switch
                  id="news-filter"
                  checked={form.news_filter ?? true}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, news_filter: v }))}
                />
              </div>
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
                    <Link href="/accounts" className="underline">Add an account</Link> first.
                  </p>
                ) : (
                  accounts.map((acc) => (
                    <div key={acc.id} className="flex items-center gap-3 rounded-lg border p-3">
                      <Checkbox
                        id={`acc-${acc.id}`}
                        checked={selectedAccounts.includes(acc.id)}
                        onCheckedChange={(checked) =>
                          setSelectedAccounts((prev) =>
                            checked ? [...prev, acc.id] : prev.filter((id) => id !== acc.id)
                          )
                        }
                      />
                      <Label htmlFor={`acc-${acc.id}`} className="flex-1 cursor-pointer">
                        <span className="font-medium">{acc.name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">#{acc.login}</span>
                      </Label>
                      <Badge variant={acc.is_live ? "destructive" : "secondary"} className="text-xs">
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
              <Button variant="outline" onClick={() => setStep((s) => s - 1)}>Back</Button>
            )}
          </div>
          <div>
            {step < 3 ? (
              <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext}>Next</Button>
            ) : (
              <Button
                onClick={handleSubmit}
                disabled={submitting || !form.name.trim() || form.symbols.length === 0}
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
