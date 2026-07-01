"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { settingsApi } from "@/lib/api/settings";
import type { GlobalSettings } from "@/types/trading";

export function NewsSection() {
  const [config, setConfig] = useState<GlobalSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const data = await settingsApi.getGlobal();
        setConfig(data);
      } catch {
        toast.error("Failed to load news settings");
      }
    })();
  }, []);

  async function handleToggle(enabled: boolean) {
    if (!config) return;
    setConfig({ ...config, news_enabled: enabled });
    setSaving(true);
    try {
      await settingsApi.patchGlobal({ news_enabled: enabled });
      toast.success(`News calendar ${enabled ? "enabled" : "disabled"}`);
    } catch {
      toast.error("Failed to update news setting");
      setConfig((prev) =>
        prev ? { ...prev, news_enabled: !enabled } : prev,
      );
    } finally {
      setSaving(false);
    }
  }

  if (!config) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">News Calendar</CardTitle>
        <CardDescription>
          Fetches the ForexFactory economic calendar daily (23:00 UTC) and
          runs LLM impact analysis on upcoming HIGH-impact events (00:00
          UTC). While enabled, a contradicting news signal can override a
          trading signal to HOLD. See the{" "}
          <a href="/news" className="underline">
            Economic Calendar
          </a>{" "}
          page to view fetched events.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Enable News Analysis</p>
            <p className="text-xs text-muted-foreground">
              Globally enable or disable the scheduled news fetch/analyze
              jobs and the news-based HOLD override in trading signals.
              Takes effect immediately, no restart needed.
            </p>
          </div>
          <Switch
            checked={config.news_enabled}
            onCheckedChange={handleToggle}
            disabled={saving}
          />
        </div>
      </CardContent>
    </Card>
  );
}
