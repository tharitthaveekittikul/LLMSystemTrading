import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountsView } from "@/components/accounts/accounts-view";
import { ConnectionStatus } from "@/components/dashboard/connection-status";

export default function AccountsPage() {
  return (
    <SidebarInset>
      <AppHeader title="Accounts">
        <ConnectionStatus />
      </AppHeader>

      <div className="flex flex-1 flex-col gap-4 p-4">
        <AccountsView />
      </div>
    </SidebarInset>
  );
}
