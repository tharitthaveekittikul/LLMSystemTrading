"use client";

import { useEffect, useState } from "react";
import { CheckCircle, Loader2, Send, XCircle } from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { settingsApi } from "@/lib/api/settings";
import type { TelegramSettings } from "@/types/trading";

export function TelegramSection() {
  const [settings, setSettings] = useState<TelegramSettings | null>(null);
  const [botToken, setBotToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    settingsApi.getTelegram().then(setSettings).catch(console.error);
  }, []);

  async function handleSave() {
    if (!botToken.trim()) {
      toast.error("Enter a bot token");
      return;
    }
    if (!chatId.trim()) {
      toast.error("Enter a chat ID");
      return;
    }
    setSaving(true);
    try {
      const updated = await settingsApi.saveTelegram(botToken.trim(), chatId.trim());
      setSettings(updated);
      setBotToken("");
      setChatId("");
      toast.success("Telegram credentials saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    try {
      const result = await settingsApi.testTelegram(botToken.trim(), chatId.trim());
      if (result.success) toast.success(result.message);
      else toast.error(result.message);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Test failed");
    } finally {
      setTesting(false);
    }
  }

  async function handleToggle(enabled: boolean) {
    setToggling(true);
    try {
      const updated = await settingsApi.patchTelegram({ is_enabled: enabled });
      setSettings(updated);
      toast.success(`Telegram alerts ${enabled ? "enabled" : "disabled"}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed");
    } finally {
      setToggling(false);
    }
  }

  const canTest = botToken.trim() && chatId.trim();
  const canSave = botToken.trim() && chatId.trim();

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Telegram Alerts</CardTitle>
            <CardDescription className="mt-1">
              Receive trade execution and kill switch notifications via Telegram.
            </CardDescription>
          </div>
          {settings?.is_configured ? (
            <Badge variant="outline" className="text-xs text-green-600 border-green-600">
              <CheckCircle className="h-3 w-3 mr-1" /> Configured
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              <XCircle className="h-3 w-3 mr-1" /> Not set
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Enable / disable toggle — only shown when configured */}
        {settings?.is_configured && (
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Enable Alerts</p>
              <p className="text-xs text-muted-foreground">
                Send Telegram messages for trades and kill-switch events
              </p>
            </div>
            <Switch
              checked={settings.is_enabled}
              onCheckedChange={handleToggle}
              disabled={toggling}
            />
          </div>
        )}

        {/* Current config hint */}
        {settings?.is_configured && (
          <div className="text-xs text-muted-foreground space-y-0.5">
            <p>
              <span className="font-medium">Bot token:</span>{" "}
              <span className="font-mono">{settings.token_hint ?? "****"}</span>
            </p>
            <p>
              <span className="font-medium">Chat ID:</span>{" "}
              <span className="font-mono">{settings.chat_id || "—"}</span>
            </p>
          </div>
        )}

        {/* Credential form */}
        <div className="space-y-3">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            {settings?.is_configured ? "Update credentials" : "Set credentials"}
          </p>
          <div className="space-y-2">
            <Label htmlFor="tg-token" className="text-sm">
              Bot Token
            </Label>
            <Input
              id="tg-token"
              type="password"
              placeholder="1234567890:ABCdef..."
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Get this from{" "}
              <span className="font-mono">@BotFather</span> on Telegram
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="tg-chat" className="text-sm">
              Chat ID
            </Label>
            <Input
              id="tg-chat"
              type="text"
              placeholder="-1001234567890"
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Your user ID or a channel/group ID (use{" "}
              <span className="font-mono">@userinfobot</span> to find yours)
            </p>
          </div>

          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="outline"
              onClick={handleTest}
              disabled={testing || (!canTest && !settings?.is_configured)}
              className="flex-1"
            >
              {testing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <Send className="h-3.5 w-3.5 mr-1" />
              )}
              Send Test
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving || !canSave}
              className="flex-1"
            >
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
              Save
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
