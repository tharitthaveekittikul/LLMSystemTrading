"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { settingsApi, type ProviderStatus, type TaskAssignment } from "@/lib/api/settings";
import { ModelSelector } from "./provider-card";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
};

const TASKS: { key: string; label: string }[] = [
  { key: "market_analysis", label: "Market Analysis" },
  { key: "vision", label: "Vision / Chart Reading" },
  { key: "execution_decision", label: "Execution Decision" },
  { key: "maintenance_technical", label: "Maintenance — Technical" },
  { key: "maintenance_sentiment", label: "Maintenance — Sentiment" },
  { key: "maintenance_decision", label: "Maintenance — Decision" },
];

interface TaskAssignmentsSectionProps {
  providers: ProviderStatus[];
}

export function TaskAssignmentsSection({ providers }: TaskAssignmentsSectionProps) {
  const [assignments, setAssignments] = useState<TaskAssignment[]>([]);
  const [saving, setSaving] = useState(false);
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
        const data = await settingsApi.getAssignments();
        setAssignments(data);
        data.forEach((a) => {
          if (a.provider) fetchModels(a.provider);
        });
      } catch {
        toast.error("Failed to load task assignments");
      }
    })();
  }, [fetchModels]);

  function update(task: string, field: "provider" | "model_name", value: string) {
    setAssignments((prev) =>
      prev.map((a) => (a.task === task ? { ...a, [field]: value } : a)),
    );
  }

  function handleProviderChange(task: string, value: string) {
    const provider = value === "none" ? "" : value;
    update(task, "provider", provider);
    update(task, "model_name", "");
    if (provider) fetchModels(provider);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await settingsApi.saveAssignments(assignments);
      setAssignments(updated);
      toast.success("Task assignments saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Task LLM Assignments</CardTitle>
        <p className="text-xs text-muted-foreground">
          Choose which provider and model handles each AI task. Only configured
          providers appear in the dropdown.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {TASKS.map(({ key, label }) => {
          const a = assignments.find((x) => x.task === key) ?? {
            task: key,
            provider: "",
            model_name: "",
          };
          const models = a.provider ? (modelOptions[a.provider] ?? []) : [];
          const isLoadingModel = a.provider ? (loadingModels[a.provider] ?? false) : false;
          return (
            <div
              key={key}
              className="rounded-md border sm:border-0 p-3 sm:p-0 bg-muted/30 sm:bg-transparent grid grid-cols-1 sm:grid-cols-[160px_1fr_1fr] gap-2 sm:gap-3 sm:items-center overflow-hidden"
            >
              <Label className="text-sm font-medium">{label}</Label>
              <Select
                value={a.provider || "none"}
                onValueChange={(v) => handleProviderChange(key, v)}
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
                  value={a.model_name || ""}
                  onValueChange={(v) => update(key, "model_name", v)}
                  models={models}
                  isLoading={isLoadingModel}
                  disabled={!a.provider}
                />
              ) : (
                <Input
                  placeholder={isLoadingModel ? "Loading models…" : "Model (e.g. gpt-4o)"}
                  value={a.model_name}
                  onChange={(e) => update(key, "model_name", e.target.value)}
                  className="font-mono text-sm"
                  disabled={!a.provider || isLoadingModel}
                />
              )}
            </div>
          );
        })}

        <Button onClick={handleSave} disabled={saving} className="mt-2">
          {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
          Save Assignments
        </Button>
      </CardContent>
    </Card>
  );
}
