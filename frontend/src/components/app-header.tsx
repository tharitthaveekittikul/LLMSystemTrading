"use client";

import { AccountSelector } from "@/components/dashboard/account-selector";
import { ConnectionStatus } from "@/components/dashboard/connection-status";
import { ThemeToggle } from "@/components/theme-toggle";
import { SidebarTrigger } from "@/components/ui/sidebar";

interface AppHeaderProps {
  title: string;
}

export function AppHeader({ title }: AppHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
      {/* Burger for mobile — hidden when sidebar is expanded (sidebar handles it in its own header) */}
      <SidebarTrigger className="md:hidden -ml-1 shrink-0" />
      <h1 className="text-base sm:text-lg font-semibold tracking-tight">
        {title}
      </h1>
      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <span className="hidden sm:flex">
          <ConnectionStatus />
        </span>
        <ThemeToggle />
        <AccountSelector />
      </div>
    </header>
  );
}
