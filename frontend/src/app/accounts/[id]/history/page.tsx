import { notFound } from "next/navigation";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountHistoryView } from "@/components/accounts/account-history-view";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AccountHistoryPage({ params }: Props) {
  const { id } = await params;
  const accountId = parseInt(id, 10);
  if (isNaN(accountId)) {
    notFound();
  }

  return (
    <SidebarInset>
      <AppHeader title="Trade History" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <AccountHistoryView accountId={accountId} />
      </div>
    </SidebarInset>
  );
}
