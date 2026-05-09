"use client";

import { AccountSelector } from "@/components/dashboard/account-selector";
import { ConnectionStatus } from "@/components/dashboard/connection-status";
import { ThemeToggle } from "@/components/theme-toggle";
import { SidebarTrigger } from "@/components/ui/sidebar";

interface AppHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  showAccountSelector?: boolean;
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
    <header className="shrink-0 sticky top-0 z-10 pt-4 px-4 bg-background">
      <div className="bg-card rounded-[24px] shadow-[var(--card-shadow)] px-5">

        {/* ── Desktop: single flex row ── */}
        <div className="hidden md:flex items-center h-16 gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-[15px] font-semibold leading-none tracking-tight truncate">
              {title}
            </h1>
            {subtitle && (
              <p className="text-[11px] text-muted-foreground/55 mt-0.5 truncate">
                {subtitle}
              </p>
            )}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
          <div className="flex items-center gap-1.5 shrink-0">
            {showConnectionStatus && <ConnectionStatus />}
            <ThemeToggle />
            {showAccountSelector && <AccountSelector />}
          </div>
        </div>

        {/* ── Mobile: two-row layout ── */}
        <div className="flex md:hidden flex-col py-3 gap-2.5">
          {/* Row 1: trigger + title + page actions + theme */}
          <div className="flex items-center gap-2.5 min-w-0">
            <SidebarTrigger className="shrink-0 h-8 w-8 rounded-full text-muted-foreground/60 hover:text-foreground transition-colors" />
            <div className="min-w-0 flex-1">
              <h1 className="text-[14px] font-semibold leading-none tracking-tight truncate">
                {title}
              </h1>
            </div>
            {actions && <div className="shrink-0">{actions}</div>}
            <ThemeToggle />
          </div>

          {/* Row 2: account selector (left) + connection status (right) */}
          {(showAccountSelector || showConnectionStatus) && (
            <div className="flex items-center gap-2 pl-1">
              {showAccountSelector && <AccountSelector />}
              {showConnectionStatus && (
                <span className="ml-auto">
                  <ConnectionStatus />
                </span>
              )}
            </div>
          )}
        </div>

      </div>
    </header>
  );
}
