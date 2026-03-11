"use client";

import { useEffect, useState } from "react";
import type { ScheduledJob } from "@/types/trading";

interface Props {
  job: ScheduledJob;
}

function formatCountdown(targetIso: string | null): string {
  if (!targetIso) return "Paused";
  const diff = new Date(targetIso).getTime() - Date.now();
  if (diff <= 0) return "Imminent…";
  const totalSecs = Math.floor(diff / 1000);
  const h = Math.floor(totalSecs / 3600);
  const m = Math.floor((totalSecs % 3600) / 60);
  const s = totalSecs % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function formatNextRunTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const CATEGORY_STYLES: Record<ScheduledJob["category"], { card: string; badge: string; dot: string }> = {
  strategy: {
    card: "border-blue-500/30 bg-blue-500/5 hover:bg-blue-500/10",
    badge: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    dot: "bg-blue-400",
  },
  system: {
    card: "border-purple-500/30 bg-purple-500/5 hover:bg-purple-500/10",
    badge: "bg-purple-500/15 text-purple-400 border-purple-500/30",
    dot: "bg-purple-400",
  },
};

const TRIGGER_BADGE: Record<ScheduledJob["trigger_type"], string> = {
  cron: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  interval: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  date: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  unknown: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};

export function ScheduledJobCard({ job }: Props) {
  const [countdown, setCountdown] = useState<string>(formatCountdown(job.next_run_time));
  const [isUrgent, setIsUrgent] = useState(false);

  useEffect(() => {
    const update = () => {
      setCountdown(formatCountdown(job.next_run_time));
      if (job.next_run_time) {
        const diff = new Date(job.next_run_time).getTime() - Date.now();
        setIsUrgent(diff > 0 && diff < 60_000);
      } else {
        setIsUrgent(false);
      }
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [job.next_run_time]);

  const styles = CATEGORY_STYLES[job.category];

  return (
    <div
      className={`relative rounded-xl border p-5 transition-colors duration-200 ${styles.card}`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${styles.dot} ${isUrgent ? "animate-pulse" : ""}`}
          />
          <p className="text-sm font-semibold leading-tight truncate">{job.name}</p>
        </div>

        {/* Trigger type badge */}
        <span
          className={`shrink-0 text-[10px] uppercase tracking-wide font-semibold px-2 py-0.5 rounded-full border ${TRIGGER_BADGE[job.trigger_type]}`}
        >
          {job.trigger_type}
        </span>
      </div>

      {/* Job ID */}
      <p className="mt-1 ml-4 text-[10px] text-muted-foreground font-mono truncate">{job.id}</p>

      {/* Schedule description */}
      <p className="mt-3 text-xs text-muted-foreground">{job.trigger_description}</p>

      {/* Divider */}
      <div className="my-3 border-t border-white/5" />

      {/* Countdown + next run */}
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-0.5">
            Next run
          </p>
          <p className="text-xs text-muted-foreground">{formatNextRunTime(job.next_run_time)}</p>
        </div>

        <div className="text-right">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-0.5">
            Countdown
          </p>
          <span
            className={`text-lg font-bold font-mono tabular-nums leading-none ${
              isUrgent ? "text-amber-400" : "text-foreground"
            }`}
          >
            {countdown}
          </span>
        </div>
      </div>
    </div>
  );
}
