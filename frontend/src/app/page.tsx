import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountOverview } from "@/components/dashboard/account-overview";
import { LivePositions } from "@/components/dashboard/live-positions";
import { AISignalsFeed } from "@/components/dashboard/ai-signals-feed";
import { KillSwitchBanner } from "@/components/dashboard/kill-switch-banner";
import { ConnectionStatus } from "@/components/dashboard/connection-status";

export default function DashboardPage() {
  return (
    <SidebarInset>
      <AppHeader title="Dashboard">
        <ConnectionStatus />
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
