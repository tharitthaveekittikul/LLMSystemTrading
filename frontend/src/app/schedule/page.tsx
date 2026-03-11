"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Timer, Cpu, Wrench } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { ScheduledJobCard } from "@/components/schedule/scheduled-job-card";
import { schedulerApi } from "@/lib/api";
import type { ScheduledJob } from "@/types/trading";

const REFRESH_INTERVAL_MS = 10_000;

function EmptyGroup({ label }: { label: string }) {
  return (
    <p className="text-sm text-muted-foreground col-span-full py-6 text-center">
      No {label.toLowerCase()} jobs scheduled.
    </p>
  );
}

export default function SchedulePage() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchJobs = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const data = await schedulerApi.getJobs();
      setJobs(data);
      setLastRefreshed(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load scheduled jobs");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchJobs(false);
  }, [fetchJobs]);

  // Auto-refresh every 10 s
  useEffect(() => {
    const id = setInterval(() => fetchJobs(true), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchJobs]);

  const strategyJobs = jobs.filter((j) => j.category === "strategy");
  const systemJobs = jobs.filter((j) => j.category === "system");

  return (
    <SidebarInset>
      <AppHeader
        title="Scheduled Tasks"
        subtitle="All active APScheduler jobs with live countdowns"
        showAccountSelector={false}
        showConnectionStatus={false}
      />

      <div className="flex-1 overflow-auto p-6 space-y-8">
        {/* Toolbar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Timer className="h-4 w-4" />
            <span>
              {jobs.length} job{jobs.length !== 1 ? "s" : ""} registered
            </span>
            {lastRefreshed && (
              <span className="ml-2 opacity-60">
                · refreshed {lastRefreshed.toLocaleTimeString()}
              </span>
            )}
          </div>

          <button
            onClick={() => fetchJobs(true)}
            disabled={refreshing || loading}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {/* Error state */}
        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="rounded-xl border border-white/5 bg-white/3 h-44 animate-pulse"
              />
            ))}
          </div>
        )}

        {!loading && (
          <>
            {/* ── Strategy Jobs ─────────────────────────────────── */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Cpu className="h-4 w-4 text-blue-400" />
                <h2 className="text-sm font-semibold text-blue-400">Strategy Jobs</h2>
                <span className="text-xs text-muted-foreground">
                  ({strategyJobs.length})
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {strategyJobs.length === 0 ? (
                  <EmptyGroup label="Strategy" />
                ) : (
                  strategyJobs.map((job) => (
                    <ScheduledJobCard key={job.id} job={job} />
                  ))
                )}
              </div>
            </section>

            {/* ── System Jobs ──────────────────────────────────── */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Wrench className="h-4 w-4 text-purple-400" />
                <h2 className="text-sm font-semibold text-purple-400">System Jobs</h2>
                <span className="text-xs text-muted-foreground">
                  ({systemJobs.length})
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {systemJobs.length === 0 ? (
                  <EmptyGroup label="System" />
                ) : (
                  systemJobs.map((job) => (
                    <ScheduledJobCard key={job.id} job={job} />
                  ))
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </SidebarInset>
  );
}
