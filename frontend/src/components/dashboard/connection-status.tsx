"use client";

import { cn } from "@/lib/utils";
import { usePing } from "@/hooks/use-ping";

export function ConnectionStatus() {
  const { latencyMs, status } = usePing();

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span
        className={cn(
          "inline-block h-2 w-2 rounded-full",
          status === "online" && "bg-green-500",
          status === "offline" && "bg-red-500",
          status === "checking" && "animate-pulse bg-yellow-500",
        )}
      />
      {status === "online" && latencyMs !== null && (
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
      {status === "offline" && (
        <span className="text-red-500">API offline</span>
      )}
      {status === "checking" && <span>connecting…</span>}
    </div>
  );
}
