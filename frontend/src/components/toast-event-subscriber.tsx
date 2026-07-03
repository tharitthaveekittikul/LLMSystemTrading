"use client";

import { useRef } from "react";
import { toast } from "sonner";
import { useWebSocket } from "@/hooks/use-websocket";
import { useTradingStore } from "@/hooks/use-trading-store";
import type {
  PipelineRunCompleteData,
  TradeRejectedData,
} from "@/types/trading";

/**
 * App-wide toast notifications for events the operator needs to know about
 * even when not looking at the page that caused them: trade executed/
 * rejected, pipeline run failed, kill-switch triggered, WS connection lost.
 * Mounted once in the root layout, next to <Toaster/>.
 *
 * Connection-lost is deduped to one toast per distinct outage (not one per
 * reconnect retry, which fires every few seconds while down) — see isDownRef.
 */
export function ToastEventSubscriber() {
  const { activeAccountId } = useTradingStore();
  const wasConnectedRef = useRef(false);
  const isDownRef = useRef(false);

  useWebSocket(
    activeAccountId,
    {
      trade_opened: (data) => {
        const d = data as { symbol: string; action: string };
        toast.success(`Trade executed — ${d.action} ${d.symbol}`);
      },
      trade_rejected: (data) => {
        const d = data as TradeRejectedData;
        toast.error(`Trade rejected — ${d.action} ${d.symbol}`, {
          description: d.error,
        });
      },
      kill_switch_triggered: (data) => {
        const d = data as { reason: string };
        toast.error("Kill switch triggered", { description: d.reason });
      },
      pipeline_run_complete: (data) => {
        const d = data as PipelineRunCompleteData;
        if (d.status === "failed") {
          toast.error(`Pipeline run failed — ${d.symbol} ${d.timeframe}`);
        }
      },
    },
    {
      onOpen: () => {
        if (wasConnectedRef.current && isDownRef.current) {
          toast.success("Connection restored");
        }
        wasConnectedRef.current = true;
        isDownRef.current = false;
      },
      onClose: () => {
        if (!wasConnectedRef.current || isDownRef.current) return;
        isDownRef.current = true;
        toast("Connection lost — reconnecting…", { duration: 4000 });
      },
    },
  );

  return null;
}
