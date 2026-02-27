// ── Account ──────────────────────────────────────────────────────────────────

export interface Account {
  id: number;
  name: string;
  broker: string;
  login: number;
  server: string;
  is_live: boolean;
  is_active: boolean;
  allowed_symbols: string[];
  max_lot_size: number;
  created_at: string;
}

export interface AccountCreatePayload {
  name: string;
  broker: string;
  login: number;
  password: string;
  server: string;
  is_live: boolean;
  allowed_symbols: string[];
  max_lot_size: number;
}

export interface AccountUpdatePayload {
  name?: string;
  broker?: string;
  server?: string;
  is_live?: boolean;
  max_lot_size?: number;
  password?: string;
}

export interface MT5AccountInfo {
  login: number;
  name: string;
  server: string;
  company: string;
  currency: string;
  leverage: number;
  balance: number;
  equity: number;
  margin: number;
  margin_free: number;
  margin_level: number;
  profit: number;
  trade_mode: number; // 0=demo, 1=contest, 2=real
}

export interface AccountBalance {
  account_id: number;
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
  id: number;
  account_id: number;
  ticket: number;
  symbol: string;
  direction: "BUY" | "SELL";
  volume: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  close_price: number | null;
  profit: number | null;
  opened_at: string;
  closed_at: string | null;
  source: "ai" | "manual";
}

// ── AI Signals ────────────────────────────────────────────────────────────────

export interface AISignal {
  id: number;
  account_id: number;
  symbol: string;
  timeframe: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  rationale: string;
  llm_provider: string;
  model_name: string;
  created_at: string;
  trade_id: number | null;
}

// ── Kill Switch ───────────────────────────────────────────────────────────────

export interface KillSwitchStatus {
  is_active: boolean;
  reason: string | null;
  activated_at: string | null;
}

// ── WebSocket Events ──────────────────────────────────────────────────────────

export type WSEventType =
  | "equity_update"
  | "positions_update"
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
  account_id: number;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number | null;
  currency: string;
  timestamp: string;
}

export interface PositionsUpdateData {
  account_id: number;
  positions: Position[];
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export interface DailyEntry {
  date: string; // "YYYY-MM-DD"
  net_pnl: number;
  trade_count: number;
}

export interface DailyPnLResponse {
  year: number;
  month: number;
  account_id: number | null;
  days: DailyEntry[];
  monthly_total: number;
  monthly_trade_count: number;
  winning_days: number;
  losing_days: number;
}

// ── Analyze Result ─────────────────────────────────────────────────────────────

export interface AnalyzeResult {
  action: "BUY" | "SELL" | "HOLD";
  entry: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  rationale: string;
  timeframe: string;
  order_placed: boolean;
  ticket: number | null;
  journal_id: number;
}

// ── Kill Switch Log ────────────────────────────────────────────────────────────

export interface KillSwitchLog {
  id: number;
  action: "activated" | "deactivated";
  reason: string | null;
  triggered_by: "system" | "user";
  created_at: string;
}
