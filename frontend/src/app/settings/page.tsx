"use client";

import { useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { settingsApi, type ProviderStatus } from "@/lib/api/settings";
import { ThemeSection } from "@/components/settings/theme-section";
import { DisplaySection } from "@/components/settings/display-section";
import { ProviderCard } from "@/components/settings/provider-card";
import { TaskAssignmentsSection } from "@/components/settings/task-assignments-section";
import { MaintenanceSection } from "@/components/settings/maintenance-section";
import { RiskManagerSection } from "@/components/settings/risk-manager-section";
import { TelegramSection } from "@/components/settings/telegram-section";

const PROVIDERS = ["openai", "gemini", "anthropic", "openrouter"] as const;

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

        <TelegramSection />

        <TaskAssignmentsSection providers={providers} />
      </div>
    </SidebarInset>
  );
}
