import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountsView } from "@/components/accounts/accounts-view";

export default function AccountsPage() {
  return (
    <SidebarInset>
      <AppHeader title="Accounts" />

      <div className="flex flex-1 flex-col gap-4 p-4">
        <AccountsView />
      </div>
    </SidebarInset>
  );
}
