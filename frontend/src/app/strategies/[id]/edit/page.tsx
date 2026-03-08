"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { strategiesApi } from "@/lib/api/strategies";
import type { Strategy } from "@/types/trading";
import { X } from "lucide-react";

type ExecMode = "llm_only" | "rule_then_llm" | "rule_only" | "hybrid_validator" | "multi_agent";
const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const STEP_LABELS = ["Basics", "Market & Schedule", "Configuration", "Review & Save"];

const EXEC_MODES: [ExecMode, string, string][] = [
  ["llm_only", "LLM Only", "LLM analyzes every candle. Requires custom_prompt."],
  ["rule_then_llm", "Rule → LLM", "Rule pre-filters; LLM validates triggered signals."],
  ["rule_only", "Rule Only", "Fully deterministic rules. Zero LLM cost."],
  ["hybrid_validator", "Hybrid Validator", "Rules open the trade; LLM validates post-entry."],
  ["multi_agent", "Multi-Agent", "Rules + LLM in parallel; consensus required."],
];

export default function EditStrategyPage() {
  const { id } = useParams<{ id: string }>();
  const strategyId = Number(id);
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [form, setForm] = useState<Partial<Strategy>>({});

  useEffect(() => {
    (async () => {
      try {
        const s = await strategiesApi.get(strategyId);
        setForm({
          name: s.name,
          description: s.description ?? undefined,
          execution_mode: s.execution_mode,
          trigger_type: s.trigger_type,
          interval_minutes: s.interval_minutes ?? undefined,
          symbols: s.symbols,
          timeframe: s.timeframe,
          lot_size: s.lot_size ?? undefined,
          sl_pips: s.sl_pips ?? undefined,
          tp_pips: s.tp_pips ?? undefined,
          news_filter: s.news_filter,
          custom_prompt: s.custom_prompt ?? undefined,
          module_path: s.module_path ?? undefined,
          class_name: s.class_name ?? undefined,
        });
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    })();
  }, [strategyId]);

  const execMode = (form.execution_mode ?? "llm_only") as ExecMode;

  function addSymbol() {
    const sym = symbolInput.trim().toUpperCase();
    const current = form.symbols ?? [];
    if (sym && !current.includes(sym)) {
      setForm((f) => ({ ...f, symbols: [...(f.symbols ?? []), sym] }));
    }
    setSymbolInput("");
  }

  function removeSymbol(sym: string) {
    setForm((f) => ({ ...f, symbols: (f.symbols ?? []).filter((s) => s !== sym) }));
  }

  async function handleSubmit() {
    setSubmitting(true);
    try {
      await strategiesApi.update(strategyId, {
        name: form.name,
        description: form.description,
        execution_mode: form.execution_mode,
        trigger_type: form.trigger_type,
        interval_minutes: form.interval_minutes,
        symbols: form.symbols,
        timeframe: form.timeframe,
        lot_size: form.lot_size,
        sl_pips: form.sl_pips,
        tp_pips: form.tp_pips,
        news_filter: form.news_filter,
        custom_prompt: form.custom_prompt,
        module_path: form.module_path,
        class_name: form.class_name,
      });
      router.push(`/strategies/${strategyId}`);
    } catch (err) {
      console.error(err);
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <SidebarInset>
        <AppHeader title="Edit Strategy" />
        <div className="p-4 text-muted-foreground">Loading...</div>
      </SidebarInset>
    );
  }

  return (
    <SidebarInset>
      <AppHeader title={`Edit: ${form.name ?? ""}`} />
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
                  value={form.name ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  value={form.description ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value || undefined }))}
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <Label>Execution Mode</Label>
                <div className="grid grid-cols-1 gap-2">
                  {EXEC_MODES.map(([mode, label, desc]) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, execution_mode: mode }))}
                      className={`text-left rounded-lg border px-3 py-2 transition-colors ${
                        execMode === mode
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      <p className="text-sm font-medium">{label}</p>
                      <p className={`text-xs mt-0.5 ${execMode === mode ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
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
                  {(form.symbols ?? []).map((sym) => (
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
                      className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                        form.timeframe === tf
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
                <Label>Trigger</Label>
                <div className="flex gap-2">
                  {(["candle_close", "interval"] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, trigger_type: t }))}
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                        form.trigger_type === t
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted"
                      }`}
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
                      onChange={(e) => setForm((f) => ({ ...f, interval_minutes: Number(e.target.value) }))}
                      className="w-24"
                    />
                    <span className="text-sm text-muted-foreground">minutes</span>
                  </div>
                )}
              </div>
            </>
          )}

          {/* Step 2: Configuration */}
          {step === 2 && (
            <>
              <h3 className="font-semibold">Step 3 — Configuration</h3>
              {execMode === "llm_only" && (
                <div className="space-y-2">
                  <Label>Custom LLM System Prompt</Label>
                  <Textarea
                    value={form.custom_prompt ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, custom_prompt: e.target.value || undefined }))}
                    className="font-mono text-sm"
                    rows={10}
                    placeholder="You are a forex trading expert..."
                  />
                </div>
              )}
              {execMode !== "llm_only" && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Module Path</Label>
                    <Input
                      value={form.module_path ?? ""}
                      onChange={(e) => setForm((f) => ({ ...f, module_path: e.target.value || undefined }))}
                      placeholder="strategies.harmonic_strategy"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Class Name</Label>
                    <Input
                      value={form.class_name ?? ""}
                      onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value || undefined }))}
                      placeholder="HarmonicStrategy"
                    />
                  </div>
                  <div className="space-y-3">
                    <Label>Risk Config (optional)</Label>
                    <div className="grid grid-cols-3 gap-3">
                      <div className="space-y-1">
                        <Label className="text-xs">Lot size</Label>
                        <Input
                          type="number"
                          step="0.01"
                          value={form.lot_size ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, lot_size: e.target.value ? Number(e.target.value) : undefined }))}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">SL pips</Label>
                        <Input
                          type="number"
                          value={form.sl_pips ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, sl_pips: e.target.value ? Number(e.target.value) : undefined }))}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">TP pips</Label>
                        <Input
                          type="number"
                          value={form.tp_pips ?? ""}
                          onChange={(e) => setForm((f) => ({ ...f, tp_pips: e.target.value ? Number(e.target.value) : undefined }))}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <Switch
                  checked={form.news_filter ?? true}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, news_filter: v }))}
                  id="news_filter"
                />
                <Label htmlFor="news_filter">News filter</Label>
              </div>
            </>
          )}

          {/* Step 3: Review */}
          {step === 3 && (
            <>
              <h3 className="font-semibold">Step 4 — Review & Save</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Name</span>
                  <span className="font-medium">{form.name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Mode</span>
                  <span className="font-medium">{form.execution_mode}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Timeframe</span>
                  <span className="font-medium">{form.timeframe}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Symbols</span>
                  <span className="font-medium">{(form.symbols ?? []).join(", ")}</span>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Navigation */}
        <div className="flex justify-between">
          <div>
            {step === 0 ? (
              <Button variant="outline" asChild>
                <Link href={`/strategies/${strategyId}`}>Cancel</Link>
              </Button>
            ) : (
              <Button variant="outline" onClick={() => setStep((s) => s - 1)}>Back</Button>
            )}
          </div>
          <div>
            {step < 3 ? (
              <Button onClick={() => setStep((s) => s + 1)}>Next</Button>
            ) : (
              <Button onClick={handleSubmit} disabled={submitting || !form.name?.trim() || !form.symbols?.length}>
                {submitting ? "Saving..." : "Save Changes"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </SidebarInset>
  );
}
