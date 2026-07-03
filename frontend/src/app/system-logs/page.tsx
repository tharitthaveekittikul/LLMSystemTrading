"use client";

import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { SystemLogView } from "@/components/system-logs/system-log-view";

export default function SystemLogsPage() {
  return (
    <SidebarInset className="h-screen overflow-hidden">
      <AppHeader
        title="System Logs"
        subtitle="Live tail or search the structured backend + frontend log stream"
        showAccountSelector={false}
        showConnectionStatus={false}
      />
      <div className="flex-1 min-h-0 overflow-hidden">
        <SystemLogView />
      </div>
    </SidebarInset>
  );
}
