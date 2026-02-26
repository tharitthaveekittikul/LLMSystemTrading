"use client";

import { cn } from "@/lib/utils";
import { usePing } from "@/hooks/use-ping";

export function ConnectionStatus() {
  const { latencyMs, apiStatus, mt5Status } = usePing();

  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      {/* API latency */}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            "inline-block h-2 w-2 rounded-full",
            apiStatus === "online" && "bg-green-500",
            apiStatus === "offline" && "bg-red-500",
            apiStatus === "checking" && "animate-pulse bg-yellow-500",
          )}
        />
        {apiStatus === "online" && latencyMs !== null && (
          <span
            className={cn(
              latencyMs < 100 && "text-green-600",
              latencyMs >= 100 && latencyMs < 300 && "text-yellow-600",
              latencyMs >= 300 && "text-red-500",
            )}
          >
            {latencyMs} ms
          </span>
        )}
        {apiStatus === "offline" && <span className="text-red-500">API offline</span>}
        {apiStatus === "checking" && <span>connecting…</span>}
      </div>

      {/* MT5 status */}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            "inline-block h-2 w-2 rounded-full",
            mt5Status === "connected" && "bg-green-500",
            mt5Status === "disconnected" && "bg-red-500",
            mt5Status === "no_accounts" && "bg-gray-400",
          )}
        />
        <span
          className={cn(
            mt5Status === "connected" && "text-green-600",
            mt5Status === "disconnected" && "text-red-500",
          )}
        >
          MT5{" "}
          {mt5Status === "connected" && "live"}
          {mt5Status === "disconnected" && "offline"}
          {mt5Status === "no_accounts" && "—"}
        </span>
      </div>
    </div>
  );
}
