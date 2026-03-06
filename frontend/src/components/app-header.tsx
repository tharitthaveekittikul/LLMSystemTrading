"use client";

import { AccountSelector } from "@/components/dashboard/account-selector";
import { ConnectionStatus } from "@/components/dashboard/connection-status";
import { ThemeToggle } from "@/components/theme-toggle";
import { SidebarTrigger } from "@/components/ui/sidebar";

interface AppHeaderProps {
  title: string;
  subtitle?: string;
  /** Right-side slot for page-specific controls (e.g. period selector, refresh button) */
  actions?: React.ReactNode;
  /** Show the account selector dropdown — default true */
  showAccountSelector?: boolean;
  /** Show the live connection status indicator — default true */
  showConnectionStatus?: boolean;
}

export function AppHeader({
  title,
  subtitle,
  actions,
  showAccountSelector = true,
  showConnectionStatus = true,
}: AppHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b px-2">
      {/* Mobile-only sidebar trigger — desktop sidebar has its own trigger in its header */}
      <SidebarTrigger className="md:hidden shrink-0" />

      {/* Title + subtitle */}
      <div className="min-w-0 flex-1 px-2">
        <h1 className="text-lg font-bold leading-none truncate">{title}</h1>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-0.5 truncate hidden sm:block">
            {subtitle}
          </p>
        )}
      </div>

      {/* Page-specific actions slot */}
      {actions && <div className="shrink-0">{actions}</div>}

      {/* Global controls */}
      <div className="flex items-center gap-2 shrink-0">
        {showConnectionStatus && (
          <span className="hidden sm:flex">
            <ConnectionStatus />
          </span>
        )}
        <ThemeToggle />
        {showAccountSelector && <AccountSelector />}
      </div>
    </header>
  );
}
