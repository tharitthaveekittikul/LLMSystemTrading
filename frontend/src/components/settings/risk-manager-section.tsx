"use client";

import { useEffect, useRef, useState } from "react";
import { settingsApi } from "@/lib/api/settings";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { RiskSettings } from "@/types/trading";

export function RiskManagerSection() {
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    settingsApi.getRisk().then(setRisk).catch(console.error);
  }, []);

  const handleChange = (patch: Partial<RiskSettings>) => {
    if (!risk) return;
    setRisk({ ...risk, ...patch });
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
    return <div className="text-sm text-muted-foreground">Loading risk settings…</div>;

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
                handleChange({ max_drawdown_pct: parseFloat(e.target.value) || 10 })
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
                handleChange({ max_open_positions: parseInt(e.target.value) || 5 })
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
                  handleChange({ rate_limit_max_trades: parseInt(e.target.value) || 3 })
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
                  handleChange({ rate_limit_window_hours: parseFloat(e.target.value) || 4 })
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
