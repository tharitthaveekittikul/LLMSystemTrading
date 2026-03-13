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
import { Switch } from "@/components/ui/switch";
import { CardDescription } from "@/components/ui/card";
import type { GlobalSettings, RiskSettings } from "@/types/trading";
import { accountsApi } from "@/lib/api/accounts";
import { useSettings } from "@/hooks/use-settings";
import type { Account } from "@/types/trading";

// ── Constants ─────────────────────────────────────────────────────────────────

const PROVIDERS = ["openai", "gemini", "anthropic", "openrouter"] as const;
type Provider = (typeof PROVIDERS)[number];

const TASKS: { key: string; label: string }[] = [
  { key: "market_analysis", label: "Market Analysis" },
  { key: "vision", label: "Vision / Chart Reading" },
  { key: "execution_decision", label: "Execution Decision" },
  { key: "maintenance_technical", label: "Maintenance — Technical" },
  { key: "maintenance_sentiment", label: "Maintenance — Sentiment" },
  { key: "maintenance_decision", label: "Maintenance — Decision" },
];

const PROVIDER_LABELS: Record<Provider, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
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

// ── Section 5: Position Maintenance ──────────────────────────────────────────

function MaintenanceSection() {
  const [config, setConfig] = useState<GlobalSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await settingsApi.getGlobal();
        setConfig(data);
      } catch {
        toast.error("Failed to load maintenance settings");
      }
    })();
  }, []);

  async function handleToggle(enabled: boolean) {
    if (!config) return;
    const updated = { ...config, maintenance_task_enabled: enabled };
    setConfig(updated);
    setSaving(true);
    try {
      await settingsApi.patchGlobal({ maintenance_task_enabled: enabled });
      toast.success(`Position maintenance ${enabled ? "enabled" : "disabled"}`);
    } catch {
      toast.error("Failed to update maintenance setting");
    } finally {
      setSaving(false);
    }
  }

  function handleIntervalChange(value: number) {
    if (!config) return;
    setConfig({ ...config, maintenance_interval_minutes: value });
    if (intervalRef.current) clearTimeout(intervalRef.current);
    intervalRef.current = setTimeout(async () => {
      try {
        await settingsApi.patchGlobal({ maintenance_interval_minutes: value });
        toast.success("Maintenance interval updated");
      } catch {
        toast.error("Failed to update interval");
      }
    }, 800);
  }

  if (!config) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Position Maintenance</CardTitle>
        <CardDescription>
          Scheduled AI review of open positions. The LLM analyzes technical
          conditions and sentiment to suggest hold, close, or modify actions.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Enable Maintenance Task</p>
            <p className="text-xs text-muted-foreground">
              Globally enable or disable the scheduled maintenance sweep
            </p>
          </div>
          <Switch
            checked={config.maintenance_task_enabled}
            onCheckedChange={handleToggle}
            disabled={saving}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="maintenance-interval">
            Maintenance Interval (minutes)
          </Label>
          <Input
            id="maintenance-interval"
            type="number"
            min={1}
            step={5}
            value={config.maintenance_interval_minutes}
            onChange={(e) => handleIntervalChange(Number(e.target.value))}
            className="w-32"
          />
          <p className="text-xs text-muted-foreground">
            How often the maintenance sweep runs (default: 60 minutes)
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 6: Risk Manager ───────────────────────────────────────────────────

function RiskManagerSection() {
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    settingsApi.getRisk().then(setRisk).catch(console.error);
  }, []);

  const handleChange = (patch: Partial<RiskSettings>) => {
    if (!risk) return;
    const updated = { ...risk, ...patch };
    setRisk(updated);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      setSaving(true);
      settingsApi
        .patchRisk(patch)
        .then(setRisk)
        .catch(console.error)
        .finally(() => setSaving(false));
    }, 800);
  };

  if (!risk)
    return (
      <div className="text-sm text-muted-foreground">
        Loading risk settings…
      </div>
    );

  return (
    <div className="space-y-4">
      {/* Drawdown Check */}
      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Drawdown Check</p>
            <p className="text-xs text-muted-foreground">
              Triggers kill switch when drawdown threshold is exceeded
            </p>
          </div>
          <Switch
            checked={risk.drawdown_check_enabled}
            onCheckedChange={(v) => handleChange({ drawdown_check_enabled: v })}
          />
        </div>
        {risk.drawdown_check_enabled && (
          <div className="flex items-center gap-2 pl-1">
            <Label className="w-40 text-xs">Max drawdown %</Label>
            <Input
              type="number"
              className="w-24 h-7 text-xs"
              value={risk.max_drawdown_pct}
              min={0.1}
              max={100}
              step={0.5}
              onChange={(e) =>
                handleChange({
                  max_drawdown_pct: parseFloat(e.target.value) || 10,
                })
              }
            />
          </div>
        )}
      </div>

      {/* Position Limit */}
      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Position Limit</p>
            <p className="text-xs text-muted-foreground">
              Reject new orders when open position count is reached
            </p>
          </div>
          <Switch
            checked={risk.position_limit_enabled}
            onCheckedChange={(v) => handleChange({ position_limit_enabled: v })}
          />
        </div>
        {risk.position_limit_enabled && (
          <div className="flex items-center gap-2 pl-1">
            <Label className="w-40 text-xs">Max open positions</Label>
            <Input
              type="number"
              className="w-24 h-7 text-xs"
              value={risk.max_open_positions}
              min={1}
              step={1}
              onChange={(e) =>
                handleChange({
                  max_open_positions: parseInt(e.target.value) || 5,
                })
              }
            />
          </div>
        )}
      </div>

      {/* Rate Limit */}
      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Rate Limit</p>
            <p className="text-xs text-muted-foreground">
              Limit entries per symbol within a rolling time window
            </p>
          </div>
          <Switch
            checked={risk.rate_limit_enabled}
            onCheckedChange={(v) => handleChange({ rate_limit_enabled: v })}
          />
        </div>
        {risk.rate_limit_enabled && (
          <div className="flex flex-col gap-2 pl-1">
            <div className="flex items-center gap-2">
              <Label className="w-40 text-xs">Max trades per symbol</Label>
              <Input
                type="number"
                className="w-24 h-7 text-xs"
                value={risk.rate_limit_max_trades}
                min={1}
                step={1}
                onChange={(e) =>
                  handleChange({
                    rate_limit_max_trades: parseInt(e.target.value) || 3,
                  })
                }
              />
            </div>
            <div className="flex items-center gap-2">
              <Label className="w-40 text-xs">Window (hours)</Label>
              <Input
                type="number"
                className="w-24 h-7 text-xs"
                value={risk.rate_limit_window_hours}
                min={0.5}
                step={0.5}
                onChange={(e) =>
                  handleChange({
                    rate_limit_window_hours: parseFloat(e.target.value) || 4,
                  })
                }
              />
            </div>
          </div>
        )}
      </div>

      {/* Hedging */}
      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Hedging Allowed</p>
            <p className="text-xs text-muted-foreground">
              Allow opening opposite-side positions on the same symbol
            </p>
          </div>
          <Switch
            checked={risk.hedging_allowed}
            onCheckedChange={(v) => handleChange({ hedging_allowed: v })}
          />
        </div>
      </div>

      {saving && <p className="text-xs text-muted-foreground">Saving…</p>}
    </div>
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
      <AppHeader
        title="Settings"
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-6xl">
        <ThemeSection />
        <DisplaySection />

        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            LLM Providers
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
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

        <MaintenanceSection />

        <Card>
          <CardHeader>
            <CardTitle>Risk Manager</CardTitle>
            <CardDescription>
              Configure and toggle individual risk rules. Changes are saved
              instantly.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RiskManagerSection />
          </CardContent>
        </Card>

        <TaskAssignmentsSection providers={providers} />
      </div>
    </SidebarInset>
  );
}
