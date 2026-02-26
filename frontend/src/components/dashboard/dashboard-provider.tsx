"use client";

import { useTradingStore } from "@/hooks/use-trading-store";
import { useWebSocket } from "@/hooks/use-websocket";
import type { EquityUpdateData, PositionsUpdateData } from "@/types/trading";

/**
 * Mounts once inside the dashboard page.
 * Opens a WebSocket for the active account and pipes events into the store.
 * Polling starts on the backend when the WS connection is established,
 * and stops automatically when the connection closes.
 */
export function DashboardProvider() {
  const { activeAccountId, setBalance, setOpenPositions, setKillSwitch } =
    useTradingStore();

  useWebSocket(activeAccountId, {
    equity_update: (data) => {
      const d = data as EquityUpdateData;
      setBalance({
        account_id: d.account_id,
        balance: d.balance,
        equity: d.equity,
        margin: d.margin,
        free_margin: d.free_margin,
        margin_level: d.margin_level,
        currency: d.currency,
        timestamp: d.timestamp,
      });
    },
    positions_update: (data) => {
      const d = data as PositionsUpdateData;
      setOpenPositions(d.positions);
    },
    kill_switch_triggered: (data) => {
      const d = data as { reason: string };
      setKillSwitch({
        is_active: true,
        reason: d.reason,
        triggered_at: new Date().toISOString(),
      });
    },
  });

  return null;
}
