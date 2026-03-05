"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import {
  Monitor,
  Moon,
  Sun,
  CheckCircle,
  XCircle,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  settingsApi,
  type ProviderStatus,
  type TaskAssignment,
} from "@/lib/api/settings";
import { accountsApi } from "@/lib/api/accounts";
import { useSettings } from "@/hooks/use-settings";
import type { Account } from "@/types/trading";

// ── Constants ─────────────────────────────────────────────────────────────────

const PROVIDERS = ["openai", "gemini", "anthropic"] as const;
type Provider = (typeof PROVIDERS)[number];

const TASKS: { key: string; label: string }[] = [
  { key: "market_analysis", label: "Market Analysis" },
  { key: "vision", label: "Vision / Chart Reading" },
  { key: "execution_decision", label: "Execution Decision" },
];

const PROVIDER_LABELS: Record<Provider, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  anthropic: "Anthropic",
};

// ── Section 1: Theme ──────────────────────────────────────────────────────────

function ThemeSection() {
  const { theme, setTheme } = useTheme();

  const options = [
    { value: "light", label: "Light", icon: <Sun className="h-4 w-4" /> },
    { value: "dark", label: "Dark", icon: <Moon className="h-4 w-4" /> },
    { value: "system", label: "System", icon: <Monitor className="h-4 w-4" /> },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Appearance</CardTitle>
      </CardHeader>
      <CardContent>
        <Label className="text-sm text-muted-foreground mb-3 block">
          Theme
        </Label>
        <div className="flex gap-2">
          {options.map((opt) => (
            <Button
              key={opt.value}
              variant={theme === opt.value ? "default" : "outline"}
              size="sm"
              className="flex items-center gap-2"
              onClick={() => setTheme(opt.value)}
            >
              {opt.icon}
              {opt.label}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 2: Display Preferences ───────────────────────────────────────────

function DisplaySection() {
  const { defaultAccountId, setDefaultAccountId } = useSettings();
  const [accounts, setAccounts] = useState<Account[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const data = await accountsApi.list();
        setAccounts(data);
      } catch {
        toast.error("Failed to load accounts");
      }
    })();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Display Preferences</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label className="text-sm">Default Account</Label>
          <p className="text-xs text-muted-foreground">
            Auto-select this account when the dashboard loads.
          </p>
          <Select
            value={defaultAccountId != null ? String(defaultAccountId) : "none"}
            onValueChange={(v) =>
              setDefaultAccountId(v === "none" ? null : Number(v))
            }
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="No default" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No default — show all</SelectItem>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={String(a.id)}>
                  {a.name} ({a.broker})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 3: Provider Card ──────────────────────────────────────────────────

interface ProviderCardProps {
  provider: Provider;
  status: ProviderStatus | undefined;
  onSaved: () => void;
}

function ProviderCard({ provider, status, onSaved }: ProviderCardProps) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  async function handleTest() {
    if (!apiKey.trim()) {
      toast.error("Enter an API key to test");
      return;
    }
    setTesting(true);
    try {
      const result = await settingsApi.testProvider(provider, apiKey);
      if (result.success) toast.success(result.message);
      else toast.error(result.message);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Test failed");
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    if (!apiKey.trim()) {
      toast.error("Enter an API key to save");
      return;
    }
    setSaving(true);
    try {
      await settingsApi.saveProvider(provider, apiKey);
      toast.success(`${PROVIDER_LABELS[provider]} API key saved`);
      setApiKey("");
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">
            {PROVIDER_LABELS[provider]}
          </CardTitle>
          {status?.is_configured ? (
            <Badge
              variant="outline"
              className="text-xs text-green-600 border-green-600"
            >
              <CheckCircle className="h-3 w-3 mr-1" /> Configured
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              <XCircle className="h-3 w-3 mr-1" /> Not set
            </Badge>
          )}
        </div>
        {status?.key_hint ? (
          <p className="text-xs text-muted-foreground font-mono">
            {status.key_hint}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground font-mono">—</p>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        <Input
          type="password"
          placeholder={`${PROVIDER_LABELS[provider]} API key`}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="font-mono text-sm"
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleTest}
            disabled={testing || !apiKey.trim()}
            className="flex-1"
          >
            {testing && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
            Test
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving || !apiKey.trim()}
            className="flex-1"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 4: Task Assignments ───────────────────────────────────────────────

interface TaskAssignmentsProps {
  providers: ProviderStatus[];
}

function TaskAssignmentsSection({ providers }: TaskAssignmentsProps) {
  const [assignments, setAssignments] = useState<TaskAssignment[]>([]);
  const [saving, setSaving] = useState(false);
  const [modelOptions, setModelOptions] = useState<Record<string, string[]>>(
    {},
  );
  const [loadingModels, setLoadingModels] = useState<Record<string, boolean>>(
    {},
  );
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

  function update(
    task: string,
    field: "provider" | "model_name",
    value: string,
  ) {
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
          const isLoadingModel = a.provider
            ? (loadingModels[a.provider] ?? false)
            : false;
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
                      {PROVIDER_LABELS[p.provider as Provider] ?? p.provider}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {models.length > 0 ? (
                <Select
                  value={a.model_name || "none"}
                  onValueChange={(v) =>
                    update(key, "model_name", v === "none" ? "" : v)
                  }
                >
                  <SelectTrigger className="font-mono text-sm w-full min-w-0 overflow-hidden">
                    <SelectValue
                      placeholder="Select model"
                      className="truncate"
                    />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— Select model —</SelectItem>
                    {models.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  placeholder={
                    isLoadingModel ? "Loading models…" : "Model (e.g. gpt-4o)"
                  }
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [providerRefresh, setProviderRefresh] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const data = await settingsApi.listProviders();
        setProviders(data);
      } catch (e) {
        console.error("Failed to load providers", e);
      }
    })();
  }, [providerRefresh]);

  return (
    <SidebarInset>
      <AppHeader title="Settings" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-3xl">
        <ThemeSection />
        <DisplaySection />

        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            LLM Providers
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {PROVIDERS.map((p) => (
              <ProviderCard
                key={p}
                provider={p}
                status={providers.find((s) => s.provider === p)}
                onSaved={() => setProviderRefresh((k) => k + 1)}
              />
            ))}
          </div>
        </div>

        <TaskAssignmentsSection providers={providers} />
      </div>
    </SidebarInset>
  );
}
