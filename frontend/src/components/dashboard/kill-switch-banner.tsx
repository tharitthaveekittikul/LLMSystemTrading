"use client";

import { ShieldAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useTradingStore } from "@/hooks/use-trading-store";

export function KillSwitchBanner() {
  const killSwitch = useTradingStore((s) => s.killSwitch);

  if (!killSwitch.is_active) return null;

  return (
    <Alert variant="destructive">
      <ShieldAlert className="h-4 w-4" />
      <AlertTitle>Kill Switch Active — All trading is halted</AlertTitle>
      <AlertDescription>
        {killSwitch.reason
          ? `Reason: ${killSwitch.reason}`
          : "No reason provided."}
      </AlertDescription>
    </Alert>
  );
}
