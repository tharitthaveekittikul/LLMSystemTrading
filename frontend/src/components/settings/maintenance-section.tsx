"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { settingsApi } from "@/lib/api/settings";
import type { GlobalSettings } from "@/types/trading";

export function MaintenanceSection() {
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
    setConfig({ ...config, maintenance_task_enabled: enabled });
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
          <Label htmlFor="maintenance-interval">Maintenance Interval (minutes)</Label>
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
