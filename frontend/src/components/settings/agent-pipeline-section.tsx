"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { settingsApi, type ProviderStatus, type TaskAssignment } from "@/lib/api/settings";
import { ModelSelector } from "./provider-card";
import type { GlobalSettings } from "@/types/trading";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
  ollama: "Ollama (Local)",
};

interface AgentPipelineSectionProps {
  providers: ProviderStatus[];
}

export function AgentPipelineSection({ providers }: AgentPipelineSectionProps) {
  const [config, setConfig] = useState<GlobalSettings | null>(null);
  const [saving, setSaving] = useState(false);

  // Indicator agent assignment (stored as task_llm_assignments row)
  const [indicatorAssignment, setIndicatorAssignment] = useState<TaskAssignment>({
    task: "indicator_agent",
    provider: "",
    model_name: "",
  });
  const [savingAssignment, setSavingAssignment] = useState(false);
  const [modelOptions, setModelOptions] = useState<Record<string, string[]>>({});
  const [loadingModels, setLoadingModels] = useState<Record<string, boolean>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  const connectedProviders = providers.filter((p) => p.is_configured);

  const fetchModels = useCallback(async (provider: string) => {
    if (!provider || fetchedRef.current.has(provider)) return;
    fetchedRef.current.add(provider);
    setLoadingModels((prev) => ({ ...prev, [provider]: true }));
    try {
      const models = await settingsApi.listProviderModels(provider);
      setModelOptions((prev) => ({ ...prev, [provider]: models }));
    } catch {
      fetchedRef.current.delete(provider);
    } finally {
      setLoadingModels((prev) => ({ ...prev, [provider]: false }));
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [globalData, assignments] = await Promise.all([
          settingsApi.getGlobal(),
          settingsApi.getAssignments(),
        ]);
        setConfig(globalData);
        const row = assignments.find((a) => a.task === "indicator_agent");
        if (row) {
          setIndicatorAssignment(row);
          if (row.provider) fetchModels(row.provider);
        }
      } catch {
        toast.error("Failed to load agent pipeline settings");
      }
    })();
  }, [fetchModels]);

  async function handleToggle(field: keyof GlobalSettings, enabled: boolean) {
    if (!config) return;
    setConfig({ ...config, [field]: enabled });
    setSaving(true);
    try {
      await settingsApi.patchGlobal({ [field]: enabled });
      toast.success("Agent pipeline setting updated");
    } catch {
      toast.error("Failed to update setting");
      setConfig((prev) => (prev ? { ...prev, [field]: !enabled } : prev));
    } finally {
      setSaving(false);
    }
  }

  function handleProviderChange(value: string) {
    const provider = value === "none" ? "" : value;
    setIndicatorAssignment((prev) => ({ ...prev, provider, model_name: "" }));
    if (provider) fetchModels(provider);
  }

  async function handleSaveAssignment() {
    setSavingAssignment(true);
    try {
      const updated = await settingsApi.saveAssignments([indicatorAssignment]);
      const row = updated.find((a) => a.task === "indicator_agent");
      if (row) setIndicatorAssignment(row);
      toast.success("Indicator agent model saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSavingAssignment(false);
    }
  }

  if (!config) return null;

  const models = indicatorAssignment.provider ? (modelOptions[indicatorAssignment.provider] ?? []) : [];
  const isLoadingModel = indicatorAssignment.provider ? (loadingModels[indicatorAssignment.provider] ?? false) : false;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Agent Pipeline</CardTitle>
        <CardDescription>
          Enable the parallel 4-agent analysis pipeline (indicator, pattern,
          trend → decision). When disabled, the standard 3-role LLM pipeline is
          used.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Master toggle */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Enable Agent Pipeline</p>
            <p className="text-xs text-muted-foreground">
              Route AI analysis through the parallel multi-agent pipeline
            </p>
          </div>
          <Switch
            checked={config.enable_agent_pipeline}
            onCheckedChange={(v) => handleToggle("enable_agent_pipeline", v)}
            disabled={saving}
          />
        </div>

        {/* Sub-toggles — only visible when master is on */}
        {config.enable_agent_pipeline && (
          <div className="pl-4 border-l-2 border-muted space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Indicator Agent</p>
                <p className="text-xs text-muted-foreground">
                  RSI, MACD, Stochastic, ROC, Williams %R analysis
                </p>
              </div>
              <Switch
                checked={config.enable_indicator_agent}
                onCheckedChange={(v) => handleToggle("enable_indicator_agent", v)}
                disabled={saving}
              />
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Pattern Agent</p>
                <p className="text-xs text-muted-foreground">
                  Visual chart pattern recognition (vision model required)
                </p>
              </div>
              <Switch
                checked={config.enable_pattern_agent}
                onCheckedChange={(v) => handleToggle("enable_pattern_agent", v)}
                disabled={saving}
              />
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Trend Agent</p>
                <p className="text-xs text-muted-foreground">
                  Trendline structure and support/resistance analysis (vision
                  model required)
                </p>
              </div>
              <Switch
                checked={config.enable_trend_agent}
                onCheckedChange={(v) => handleToggle("enable_trend_agent", v)}
                disabled={saving}
              />
            </div>

            {/* Indicator Agent Model Assignment */}
            <div className="space-y-2 pt-2 border-t">
              <div>
                <Label className="text-sm font-medium">Indicator Agent Model Override</Label>
                <p className="text-xs text-muted-foreground">
                  Use a cheaper model for the indicator agent. Leave empty to use the provider default.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2 sm:items-center">
                <Select
                  value={indicatorAssignment.provider || "none"}
                  onValueChange={handleProviderChange}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Provider" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— Not set —</SelectItem>
                    {connectedProviders.map((p) => (
                      <SelectItem key={p.provider} value={p.provider}>
                        {PROVIDER_LABELS[p.provider] ?? p.provider}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {models.length > 0 ? (
                  <ModelSelector
                    value={indicatorAssignment.model_name || ""}
                    onValueChange={(v) =>
                      setIndicatorAssignment((prev) => ({ ...prev, model_name: v }))
                    }
                    models={models}
                    isLoading={isLoadingModel}
                    disabled={!indicatorAssignment.provider}
                  />
                ) : (
                  <Input
                    placeholder={isLoadingModel ? "Loading models…" : "Model (e.g. gpt-4o-mini)"}
                    value={indicatorAssignment.model_name}
                    onChange={(e) =>
                      setIndicatorAssignment((prev) => ({ ...prev, model_name: e.target.value }))
                    }
                    className="font-mono text-sm"
                    disabled={!indicatorAssignment.provider || isLoadingModel}
                  />
                )}

                <Button
                  size="sm"
                  onClick={handleSaveAssignment}
                  disabled={savingAssignment}
                >
                  {savingAssignment && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
                  Save
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
