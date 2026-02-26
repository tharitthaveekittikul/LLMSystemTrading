"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE_URL, API_V1 } from "@/lib/api";

export type PingStatus = "checking" | "online" | "offline";
export type MT5Status = "connected" | "disconnected" | "no_accounts";

export interface MT5AccountState {
  account_id: number;
  is_connected: boolean;
  last_polled_at: string | null;
  last_error: string | null;
}

export function usePing(intervalMs = 5000) {
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [apiStatus, setApiStatus] = useState<PingStatus>("checking");
  const [mt5Status, setMt5Status] = useState<MT5Status>("no_accounts");
  const [mt5Accounts, setMt5Accounts] = useState<MT5AccountState[]>([]);

  const ping = useCallback(async () => {
    // ── Network latency (hit /health)
    const start = performance.now();
    try {
      await fetch(`${API_BASE_URL}/health`, {
        method: "GET",
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      setLatencyMs(Math.round(performance.now() - start));
      setApiStatus("online");
    } catch {
      setLatencyMs(null);
      setApiStatus("offline");
      setMt5Status("disconnected");
      return; // no point checking MT5 if API is down
    }

    // ── MT5 poller status
    try {
      const res = await fetch(`${API_V1}/status`, {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      const data = await res.json() as { poller_running: boolean; accounts: MT5AccountState[] };
      setMt5Accounts(data.accounts);

      if (data.accounts.length === 0) {
        setMt5Status("no_accounts");
      } else if (data.accounts.some((a) => a.is_connected)) {
        setMt5Status("connected");
      } else {
        setMt5Status("disconnected");
      }
    } catch {
      setMt5Status("disconnected");
    }
  }, []);

  useEffect(() => {
    ping();
    const id = setInterval(ping, intervalMs);
    return () => clearInterval(id);
  }, [ping, intervalMs]);

  // Keep legacy `status` alias so ConnectionStatus doesn't break
  return { latencyMs, status: apiStatus, apiStatus, mt5Status, mt5Accounts };
}
