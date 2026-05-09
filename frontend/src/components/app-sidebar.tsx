"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Activity,
  BarChart3,
  Brain,
  CandlestickChart,
  Coins,
  Cpu,
  Database,
  FlaskConical,
  LayoutDashboard,
  Monitor,
  Network,
  Newspaper,
  ScrollText,
  Settings,
  Shield,
  SlidersHorizontal,
  Timer,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarTrigger,
} from "@/components/ui/sidebar";

const tradingItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chart", label: "Chart", icon: CandlestickChart },
  { href: "/accounts", label: "Accounts", icon: Users },
  { href: "/strategies", label: "Strategies", icon: Cpu },
  { href: "/trades", label: "Trades", icon: TrendingUp },
  { href: "/signals", label: "AI Signals", icon: Brain },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
  { href: "/backtest/optimize", label: "Optimize", icon: SlidersHorizontal },
];

const systemItems = [
  { href: "/logs", label: "Pipeline Logs", icon: ScrollText },
  { href: "/agent-workflow", label: "Agent Workflow", icon: Network },
  { href: "/schedule", label: "Schedule", icon: Timer },
  { href: "/llm-usage", label: "LLM Usage", icon: Coins },
  { href: "/llm-analytics", label: "LLM Analytics", icon: Activity },
  { href: "/storage", label: "Storage", icon: Database },
  { href: "/system-usage", label: "System Usage", icon: Monitor },
  { href: "/kill-switch", label: "Kill Switch", icon: Shield },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavItem({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      title={label}
      className={cn(
        /* expanded: left/right margin + pill padding */
        "mx-3 flex items-center gap-3 px-3 py-2.5 rounded-full",
        "text-[14px] tracking-wide transition-colors duration-150",
        /* collapsed: centered square pill */
        "group-data-[collapsible=icon]:mx-auto group-data-[collapsible=icon]:w-8 group-data-[collapsible=icon]:h-8 group-data-[collapsible=icon]:p-0 group-data-[collapsible=icon]:gap-0 group-data-[collapsible=icon]:justify-center",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-semibold"
          : "text-sidebar-foreground/55 hover:text-sidebar-foreground hover:bg-sidebar-border/50",
      )}
    >
      <Icon className="h-[18px] w-[18px] shrink-0 group-data-[collapsible=icon]:h-4 group-data-[collapsible=icon]:w-4" strokeWidth={1.3} />
      <span className="group-data-[collapsible=icon]:hidden truncate">{label}</span>
    </Link>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-6 mb-2 mt-1 text-[10px] font-semibold tracking-[0.12em] uppercase text-sidebar-foreground/35 group-data-[collapsible=icon]:hidden">
      {children}
    </p>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Sidebar collapsible="icon">
      {/* Header */}
      <SidebarHeader>
        <div className="flex h-[72px] items-center justify-between px-5 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <span className="text-[13px] font-semibold tracking-[0.06em] uppercase text-sidebar-foreground/60 group-data-[collapsible=icon]:hidden select-none">
            LLM Trading
          </span>
          <SidebarTrigger className="h-8 w-8 rounded-full text-sidebar-foreground/40 hover:text-sidebar-foreground hover:bg-sidebar-border/50 transition-colors shrink-0" />
        </div>
      </SidebarHeader>

      {/* Header divider */}
      <div className="mx-5 h-px bg-sidebar-border shrink-0 group-data-[collapsible=icon]:mx-3" />

      {/* Nav */}
      <SidebarContent className="py-3 gap-0">
        <div className="flex flex-col gap-0.5">
          <SectionLabel>Trading</SectionLabel>
          {tradingItems.map((item) => (
            <NavItem key={item.href} {...item} active={isActive(item.href)} />
          ))}
        </div>

        {/* Section divider */}
        <div className="mx-5 h-px bg-sidebar-border/60 my-3 group-data-[collapsible=icon]:mx-3 shrink-0" />

        <div className="flex flex-col gap-0.5">
          <SectionLabel>System</SectionLabel>
          {systemItems.map((item) => (
            <NavItem key={item.href} {...item} active={isActive(item.href)} />
          ))}
        </div>
      </SidebarContent>

      {/* Footer */}
      <SidebarFooter className="px-5 py-4 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:py-3">
        <div className="flex items-center gap-2.5 group-data-[collapsible=icon]:justify-center">
          <span className="size-1.5 shrink-0 rounded-full bg-emerald-500/60" />
          <span className="text-[11px] text-sidebar-foreground/30 tracking-wide group-data-[collapsible=icon]:hidden">
            system running
          </span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
