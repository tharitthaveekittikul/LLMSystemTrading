import { AccountSelector } from "@/components/dashboard/account-selector";
import { ConnectionStatus } from "@/components/dashboard/connection-status";

interface AppHeaderProps {
  title: string;
}

export function AppHeader({ title }: AppHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
      <h1 className="font-semibold">{title}</h1>
      <div className="ml-auto flex items-center gap-3">
        <ConnectionStatus />
        <AccountSelector />
      </div>
    </header>
  );
}
