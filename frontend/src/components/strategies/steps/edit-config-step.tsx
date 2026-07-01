import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { ModelSelector } from "@/components/settings/provider-card";
import { StrategyClassSelector } from "@/components/strategies/strategy-class-selector";
import { StrategyParamsForm } from "@/components/strategies/strategy-params-form";
import type { Strategy, StrategyRegistryEntry } from "@/types/trading";

type ExecMode =
  | "llm_only"
  | "rule_then_llm"
  | "rule_only"
  | "hybrid_validator"
  | "multi_agent";

interface EditConfigStepProps {
  form: Partial<Strategy>;
  setForm: React.Dispatch<React.SetStateAction<Partial<Strategy>>>;
  execMode: ExecMode;
  isLlmMode: boolean;
  registryEntries: StrategyRegistryEntry[];
  selectedEntry: StrategyRegistryEntry | null;
  strategyParamValues: Record<string, unknown>;
  setStrategyParamValues: (values: Record<string, unknown>) => void;
  showCustomClass: boolean;
  setShowCustomClass: (fn: (v: boolean) => boolean) => void;
  modelOptions: string[];
  loadingModels: boolean;
  selectRegistryEntry: (key: string) => void;
}

export function EditConfigStep({
  form,
  setForm,
  execMode,
  isLlmMode,
  registryEntries,
  selectedEntry,
  strategyParamValues,
  setStrategyParamValues,
  showCustomClass,
  setShowCustomClass,
  modelOptions,
  loadingModels,
  selectRegistryEntry,
}: EditConfigStepProps) {
  return (
    <>
      <h3 className="font-semibold">Step 3 — Configuration</h3>

      {execMode === "llm_only" && (
        <div className="space-y-2">
          <Label>Custom LLM System Prompt</Label>
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
            placeholder="You are a forex trading expert..."
          />
        </div>
      )}

      {execMode !== "llm_only" && (
        <div className="space-y-5">
          {/* Registry selector */}
          <div className="space-y-2">
            <Label>Strategy Class</Label>
            <p className="text-xs text-muted-foreground">
              Select a registered strategy. Parameters will appear below.
            </p>
            <StrategyClassSelector
              entries={registryEntries.filter(
                (e) => e.execution_mode === execMode
              )}
              value={form.strategy_key ?? null}
              onChange={selectRegistryEntry}
            />
            {registryEntries.filter((e) => e.execution_mode === execMode).length === 0 && (
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

          {/* Custom class fallback */}
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

      <div className="flex items-center justify-between rounded-lg border p-3">
        <div className="space-y-0.5">
          <Label className="text-sm font-medium cursor-pointer" htmlFor="news_filter">
            News Filter
          </Label>
          <p className="text-xs text-muted-foreground">
            Pause trading around high-impact news events
          </p>
        </div>
        <Switch
          checked={form.news_filter ?? true}
          onCheckedChange={(v) =>
            setForm((f) => ({ ...f, news_filter: v }))
          }
          id="news_filter"
        />
      </div>
      {/* LLM Provider override (only for LLM-capable modes) */}
      {isLlmMode && (
        <div className="space-y-3 rounded-lg border p-4">
          <div className="space-y-0.5">
            <p className="text-sm font-medium">LLM Provider Override</p>
            <p className="text-xs text-muted-foreground">
              Optional. Override the global provider for this strategy. Leave blank to use the server default.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Provider</Label>
            <div className="flex gap-2 flex-wrap">
              {(["", "openai", "gemini", "anthropic", "openrouter", "ollama"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() =>
                    setForm((s) => ({
                      ...s,
                      llm_provider: p || undefined,
                      llm_model: p ? s.llm_model : undefined,
                    }))
                  }
                  className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                    (form.llm_provider ?? "") === p
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-background hover:bg-muted"
                  }`}
                >
                  {p === "" ? "Default" : p}
                </button>
              ))}
            </div>
          </div>
          {form.llm_provider && (
            <div className="space-y-1.5">
              <Label className="text-xs">
                Model Name <span className="text-destructive">*</span>
              </Label>
              {loadingModels ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground h-9 px-3 rounded-md border border-input bg-background opacity-50">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Loading models...
                </div>
              ) : modelOptions.length > 0 ? (
                <ModelSelector
                  value={form.llm_model ?? ""}
                  onValueChange={(v) =>
                    setForm((s) => ({ ...s, llm_model: v || undefined }))
                  }
                  models={modelOptions}
                  isLoading={loadingModels}
                  disabled={false}
                />
              ) : (
                <Input
                  value={form.llm_model ?? ""}
                  onChange={(e) =>
                    setForm((s) => ({
                      ...s,
                      llm_model: e.target.value || undefined,
                    }))
                  }
                  placeholder={
                    form.llm_provider === "openai" ? "e.g. gpt-4o" :
                    form.llm_provider === "anthropic" ? "e.g. claude-sonnet-4-6" :
                    form.llm_provider === "gemini" ? "e.g. gemini-1.5-pro" :
                    form.llm_provider === "ollama" ? "e.g. llama3.1:8b" :
                    "e.g. openai/gpt-4o"
                  }
                />
              )}
              {form.llm_provider && !form.llm_model?.trim() && !loadingModels && (
                <p className="text-xs text-destructive">
                  Model name is required when a provider is selected.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between py-2 border-t">
        <div>
          <p className="text-sm font-medium">Position Maintenance</p>
          <p className="text-xs text-muted-foreground">
            Allow AI to review and manage positions opened by this
            strategy
          </p>
        </div>
        <Switch
          checked={form.maintenance_enabled ?? true}
          onCheckedChange={(v) =>
            setForm((f) => ({ ...f, maintenance_enabled: v }))
          }
          id="maintenance_enabled"
        />
      </div>
    </>
  );
}
