"use client";

import { useCallback } from "react";
import { useTradingStore } from "@/hooks/use-trading-store";
import { useWebSocket } from "@/hooks/use-websocket";
import type { EquityPoint, EquityUpdateData, PendingOrdersUpdateData, PositionsUpdateData } from "@/types/trading";

interface DashboardProviderProps {
  onEquityUpdate?: (point: EquityPoint) => void;
}

export function DashboardProvider({ onEquityUpdate }: DashboardProviderProps) {
  const { activeAccountId, setBalance, setOpenPositions, setPendingOrders, setKillSwitch } =
    useTradingStore();

  const handleEquityUpdate = useCallback(
    (data: unknown) => {
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
      if (onEquityUpdate) {
        onEquityUpdate({ ts: d.timestamp, equity: d.equity, balance: d.balance });
      }
    },
    [setBalance, onEquityUpdate]
  );

  useWebSocket(activeAccountId, {
    equity_update: handleEquityUpdate,
    positions_update: (data) => {
      const d = data as PositionsUpdateData;
      setOpenPositions(d.positions);
    },
    pending_orders_update: (data) => {
      const d = data as PendingOrdersUpdateData;
      setPendingOrders(d.orders);
    },
    kill_switch_triggered: (data) => {
      const d = data as { reason: string };
      setKillSwitch({ is_active: true, reason: d.reason, activated_at: new Date().toISOString() });
    },
  });

  return null;
}
