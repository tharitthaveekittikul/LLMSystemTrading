"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/use-websocket";
import { useTradingStore } from "@/hooks/use-trading-store";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { logsApi } from "@/lib/api";
import { formatDateTime } from "@/lib/date";
import type { SystemLogWsData } from "@/types/trading";

const LEVEL_STYLES: Record<string, string> = {
  DEBUG: "bg-muted text-muted-foreground",
  INFO: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  WARNING: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  ERROR: "bg-red-500/15 text-red-700 dark:text-red-400",
  CRITICAL: "bg-red-600/20 text-red-800 dark:text-red-300",
};

const MAX_LIVE_LINES = 500;
const PAGE_SIZE = 100;

export function SystemLogView() {
  const { activeAccountId } = useTradingStore();
  const [mode, setMode] = useState<"live" | "search">("live");
  const [levelFilter, setLevelFilter] = useState("all");
  const [loggerFilter, setLoggerFilter] = useState("");

  // ── Live tail ──────────────────────────────────────────────────────────────
  const [liveLines, setLiveLines] = useState<SystemLogWsData[]>([]);
  const [paused, setPaused] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useWebSocket(activeAccountId, {
    system_log: (data) => {
      const line = data as SystemLogWsData;
      setLiveLines((prev) => {
        if (paused) return prev;
        const next = [...prev, line];
        return next.length > MAX_LIVE_LINES
          ? next.slice(next.length - MAX_LIVE_LINES)
          : next;
      });
    },
  });

  useEffect(() => {
    if (mode === "live" && !paused) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [liveLines, mode, paused]);

  const filteredLiveLines = liveLines.filter((l) => {
    if (levelFilter !== "all" && l.level !== levelFilter.toUpperCase()) return false;
    if (loggerFilter.trim() && !l.logger.includes(loggerFilter.trim())) return false;
    return true;
  });

  // ── Search ─────────────────────────────────────────────────────────────────
  const [searchEntries, setSearchEntries] = useState<SystemLogWsData[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [totalMatched, setTotalMatched] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const runSearch = useCallback(
    async (nextOffset: number) => {
      setSearchLoading(true);
      try {
        const page = await logsApi.listSystemLogs({
          level: levelFilter !== "all" ? levelFilter : undefined,
          logger: loggerFilter.trim() || undefined,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setSearchEntries(page.entries);
        setTotalMatched(page.total_matched);
        setHasMore(page.has_more);
        setOffset(nextOffset);
      } catch (e) {
        console.error(e);
      } finally {
        setSearchLoading(false);
      }
    },
    [levelFilter, loggerFilter],
  );

  useEffect(() => {
    if (mode === "search") {
      runSearch(0);
    }
    // Filters changing while in search mode should re-query from the top.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, levelFilter, loggerFilter]);

  const rows = mode === "live" ? filteredLiveLines : searchEntries;

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="p-3 border-b flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {(["live", "search"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={[
                "rounded px-3 py-1 text-xs font-medium transition-colors",
                mode === m
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-accent",
              ].join(" ")}
            >
              {m === "live" ? "● Live" : "Search"}
            </button>
          ))}
        </div>

        <Select value={levelFilter} onValueChange={setLevelFilter}>
          <SelectTrigger className="h-8 w-32 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All levels</SelectItem>
            <SelectItem value="debug">Debug</SelectItem>
            <SelectItem value="info">Info</SelectItem>
            <SelectItem value="warning">Warning</SelectItem>
            <SelectItem value="error">Error</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
          </SelectContent>
        </Select>

        <Input
          placeholder="Filter by logger (e.g. mt5.bridge)"
          value={loggerFilter}
          onChange={(e) => setLoggerFilter(e.target.value)}
          className="h-8 w-56 text-sm"
        />

        {mode === "live" && (
          <button
            onClick={() => setPaused((p) => !p)}
            className="ml-auto rounded px-3 py-1 text-xs font-medium bg-muted text-muted-foreground hover:bg-accent"
          >
            {paused ? "Resume" : "Pause"}
          </button>
        )}

        {mode === "search" && (
          <span className="ml-auto text-xs text-muted-foreground">
            {totalMatched} matched
          </span>
        )}
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-y-auto font-mono text-xs">
        {mode === "search" && searchLoading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground font-sans">
            {mode === "live" ? "Waiting for log lines…" : "No matching log lines."}
          </p>
        ) : (
          <div className="divide-y">
            {rows.map((line, i) => (
              <div
                key={i}
                className="px-3 py-1.5 flex items-start gap-2 hover:bg-accent/40"
              >
                <span className="text-muted-foreground shrink-0">
                  {formatDateTime(line.ts)}
                </span>
                <Badge
                  variant="outline"
                  className={`shrink-0 text-[10px] px-1 py-0 ${LEVEL_STYLES[line.level] ?? ""}`}
                >
                  {line.level}
                </Badge>
                <span className="text-muted-foreground shrink-0 truncate max-w-[160px]">
                  {line.logger}
                </span>
                <span className="flex-1 break-all">{line.message}</span>
                {line.run_id != null && (
                  <span className="text-muted-foreground shrink-0">
                    run={line.run_id}
                  </span>
                )}
                {line.account_id != null && (
                  <span className="text-muted-foreground shrink-0">
                    acct={line.account_id}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Pagination (search mode) */}
      {mode === "search" && (
        <div className="p-2 border-t flex items-center justify-center gap-2 text-xs">
          <button
            disabled={offset === 0}
            onClick={() => runSearch(Math.max(0, offset - PAGE_SIZE))}
            className="rounded px-2 py-1 disabled:opacity-40 hover:bg-accent"
          >
            ‹ Prev
          </button>
          <span className="text-muted-foreground">
            {totalMatched === 0 ? 0 : offset + 1}–
            {Math.min(offset + PAGE_SIZE, totalMatched)} of {totalMatched}
          </span>
          <button
            disabled={!hasMore}
            onClick={() => runSearch(offset + PAGE_SIZE)}
            className="rounded px-2 py-1 disabled:opacity-40 hover:bg-accent"
          >
            Next ›
          </button>
        </div>
      )}
    </div>
  );
}
