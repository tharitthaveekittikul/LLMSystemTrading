"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle, Loader2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { settingsApi, type ProviderStatus } from "@/lib/api/settings";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
};

// ── ModelSelector ──────────────────────────────────────────────────────────────

interface ModelSelectorProps {
  value: string;
  onValueChange: (v: string) => void;
  models: string[];
  isLoading: boolean;
  disabled: boolean;
}

export function ModelSelector({
  value,
  onValueChange,
  models,
  isLoading,
  disabled,
}: ModelSelectorProps) {
  const [search, setSearch] = useState(value);

  useEffect(() => {
    setSearch(value);
  }, [value]);

  const filteredModels = useMemo(() => {
    if (!search || search === value) return models;
    return models.filter((m) => m.toLowerCase().includes(search.toLowerCase()));
  }, [models, search, value]);

  return (
    <Combobox
      value={value}
      onValueChange={(v) => {
        const next = v ?? "";
        onValueChange(next);
        setSearch(next);
      }}
    >
      <ComboboxInput
        placeholder={isLoading ? "Loading models…" : "Select model"}
        className="font-mono text-sm w-full"
        showClear={true}
        disabled={disabled || isLoading}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <ComboboxContent className="min-w-[200px]">
        <ComboboxList>
          {filteredModels.map((m) => (
            <ComboboxItem key={m} value={m}>
              {m}
            </ComboboxItem>
          ))}
        </ComboboxList>
        <ComboboxEmpty>No models found</ComboboxEmpty>
      </ComboboxContent>
    </Combobox>
  );
}

// ── ProviderCard ───────────────────────────────────────────────────────────────

interface ProviderCardProps {
  provider: string;
  status: ProviderStatus | undefined;
  onSaved: () => void;
}

export function ProviderCard({ provider, status, onSaved }: ProviderCardProps) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const label = PROVIDER_LABELS[provider] ?? provider;

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
      toast.success(`${label} API key saved`);
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
          <CardTitle className="text-sm font-semibold">{label}</CardTitle>
          {status?.is_configured ? (
            <Badge variant="outline" className="text-xs text-green-600 border-green-600">
              <CheckCircle className="h-3 w-3 mr-1" /> Configured
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              <XCircle className="h-3 w-3 mr-1" /> Not set
            </Badge>
          )}
        </div>
        {status?.key_hint ? (
          <p className="text-xs text-muted-foreground font-mono">{status.key_hint}</p>
        ) : (
          <p className="text-xs text-muted-foreground font-mono">—</p>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        <Input
          type="password"
          placeholder={`${label} API key`}
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
