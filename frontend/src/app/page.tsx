import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountOverview } from "@/components/dashboard/account-overview";
import { LivePositions } from "@/components/dashboard/live-positions";
import { AISignalsFeed } from "@/components/dashboard/ai-signals-feed";
import { KillSwitchBanner } from "@/components/dashboard/kill-switch-banner";
import { ConnectionStatus } from "@/components/dashboard/connection-status";
import { AccountSelector } from "@/components/dashboard/account-selector";
import { DashboardProvider } from "@/components/dashboard/dashboard-provider";

export default function DashboardPage() {
  return (
    <SidebarInset>
      <DashboardProvider />

      <AppHeader title="Dashboard">
        <div className="flex items-center gap-3">
          <ConnectionStatus />
          <AccountSelector />
        </div>
      </AppHeader>

      <div className="flex flex-1 flex-col gap-4 p-4">
        <KillSwitchBanner />

        <div className="grid auto-rows-min gap-4 md:grid-cols-3">
          <AccountOverview />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <LivePositions />
          <AISignalsFeed />
        </div>
      </div>
    </SidebarInset>
  );
}
