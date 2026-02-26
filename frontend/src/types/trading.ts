// ── Account ──────────────────────────────────────────────────────────────────

export interface Account {
  id: string;
  name: string;
  broker: string;
  login: string;
  server: string;
  is_active: boolean;
  created_at: string;
}

export interface AccountBalance {
  account_id: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number | null;
  currency: string;
  timestamp: string;
}

// ── Positions & Trades ────────────────────────────────────────────────────────

export interface Position {
  ticket: number;
  symbol: string;
  type: "buy" | "sell";
  volume: number;
  open_price: number;
  current_price: number;
  sl: number | null;
  tp: number | null;
  profit: number;
  swap: number;
  open_time: string;
}

export interface Trade {
  id: string;
  account_id: string;
  ticket: number;
  symbol: string;
  type: "buy" | "sell";
  volume: number;
  open_price: number;
  close_price: number | null;
  sl: number | null;
  tp: number | null;
  open_time: string;
  close_time: string | null;
  profit: number | null;
  swap: number | null;
  ai_signal_id: string | null;
  status: "open" | "closed" | "cancelled";
}

// ── AI Signals ────────────────────────────────────────────────────────────────

export interface AISignal {
  id: string;
  account_id: string;
  symbol: string;
  action: "buy" | "sell" | "hold" | "close";
  confidence: number;
  reasoning: string;
  provider: string;
  model: string;
  created_at: string;
  executed: boolean;
  trade_id: string | null;
}

// ── Kill Switch ───────────────────────────────────────────────────────────────

export interface KillSwitchStatus {
  is_active: boolean;
  reason: string | null;
  triggered_at: string | null;
}

// ── WebSocket Events ──────────────────────────────────────────────────────────

export type WSEventType =
  | "equity_update"
  | "trade_opened"
  | "trade_closed"
  | "ai_signal"
  | "kill_switch_triggered";

export interface WSEvent<T = unknown> {
  event: WSEventType;
  data: T;
  timestamp: string;
}

export interface EquityUpdateData {
  account_id: string;
  equity: number;
  balance: number;
  margin: number;
  free_margin: number;
}
