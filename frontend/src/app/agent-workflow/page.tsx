"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Brain, Network, Newspaper, Shield } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { TabMarket } from "@/components/agent-workflow/tab-market";
import { TabMaintenance } from "@/components/agent-workflow/tab-maintenance";
import { TabNews } from "@/components/agent-workflow/tab-news";
import { ContextMap } from "@/components/agent-workflow/context-map";

export default function AgentWorkflowPage() {
  return (
    <div className="flex flex-col h-full w-full">
      <AppHeader
        title="Agent Collaboration Workflows"
        subtitle="How LLM agents collaborate — what context each agent receives, produces, and shares with others."
        showAccountSelector={false}
      />

      <div className="space-y-6 p-6">
        {/* Legend */}
        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-xs">
          <span className="font-semibold text-muted-foreground mr-1">
            Legend:
          </span>
          <div className="flex items-center gap-1 rounded border border-blue-500/40 bg-blue-500/10 px-2 py-0.5">
            <span className="text-blue-400">·</span>
            <span className="text-blue-300">Input</span>
          </div>
          <div className="flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5">
            <span className="text-emerald-400">→</span>
            <span className="text-emerald-300">Output</span>
          </div>
          <div className="flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5">
            <span className="text-amber-400">⇢</span>
            <span className="text-amber-300">
              Shared context (from another agent)
            </span>
          </div>
          <div className="flex items-center gap-1 rounded border border-slate-600 bg-slate-800/50 px-2 py-0.5">
            <span className="text-slate-400">○</span>
            <span className="text-slate-400">Optional input</span>
          </div>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="market">
          <TabsList>
            <TabsTrigger value="market" className="gap-2">
              <Brain className="h-4 w-4" />
              Market Analysis
            </TabsTrigger>
            <TabsTrigger value="maintenance" className="gap-2">
              <Shield className="h-4 w-4" />
              Position Maintenance
            </TabsTrigger>
            <TabsTrigger value="news" className="gap-2">
              <Newspaper className="h-4 w-4" />
              News Pipelines
            </TabsTrigger>
          </TabsList>

          <TabsContent value="market">
            <TabMarket />
          </TabsContent>

          <TabsContent value="maintenance">
            <TabMaintenance />
          </TabsContent>

          <TabsContent value="news">
            <TabNews />
          </TabsContent>
        </Tabs>

        {/* System-wide context map */}
        <ContextMap />
      </div>
    </div>
  );
}
