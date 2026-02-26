"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE_URL } from "@/lib/api";

export type PingStatus = "checking" | "online" | "offline";

export function usePing(intervalMs = 5000) {
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [status, setStatus] = useState<PingStatus>("checking");

  const ping = useCallback(async () => {
    const start = performance.now();
    try {
      await fetch(`${API_BASE_URL}/health`, {
        method: "GET",
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      const ms = Math.round(performance.now() - start);
      setLatencyMs(ms);
      setStatus("online");
    } catch {
      setLatencyMs(null);
      setStatus("offline");
    }
  }, []);

  useEffect(() => {
    ping();
    const id = setInterval(ping, intervalMs);
    return () => clearInterval(id);
  }, [ping, intervalMs]);

  return { latencyMs, status };
}
