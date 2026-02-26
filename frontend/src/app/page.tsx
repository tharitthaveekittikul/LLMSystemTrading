import { SidebarInset, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { AccountOverview } from "@/components/dashboard/account-overview";
import { LivePositions } from "@/components/dashboard/live-positions";
import { AISignalsFeed } from "@/components/dashboard/ai-signals-feed";
import { KillSwitchBanner } from "@/components/dashboard/kill-switch-banner";
import { ConnectionStatus } from "@/components/dashboard/connection-status";

export default function DashboardPage() {
  return (
    <SidebarInset>
      <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-2 h-4" />
        <h1 className="font-semibold">Dashboard</h1>
        <div className="ml-auto">
          <ConnectionStatus />
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-4">
        <KillSwitchBanner />

        {/* Account stat cards */}
        <div className="grid auto-rows-min gap-4 md:grid-cols-3">
          <AccountOverview />
        </div>

        {/* Live data panels */}
        <div className="grid gap-4 md:grid-cols-2">
          <LivePositions />
          <AISignalsFeed />
        </div>
      </div>
    </SidebarInset>
  );
}
