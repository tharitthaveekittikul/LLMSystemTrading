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
  risk_pct: number;
  auto_trade_enabled: boolean;
  created_at: string;
  mt5_path: string;
  account_type: string;
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
  risk_pct?: number;
  mt5_path?: string;
  account_type?: string;
}

export interface AccountUpdatePayload {
  name?: string;
  broker?: string;
  server?: string;
  is_live?: boolean;
  max_lot_size?: number;
  risk_pct?: number;
  auto_trade_enabled?: boolean;
  password?: string;
  mt5_path?: string;
  account_type?: string;
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
  | "kill_switch_triggered"
  | "pipeline_run_complete";

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
  currency: string;
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

// ── Account Stats & Equity History ────────────────────────────────────────────

export interface AccountStats {
  win_rate: number;
  total_pnl: number;
  trade_count: number;
  winning_trades: number;
}

export interface EquityPoint {
  ts: string;
  equity: number;
  balance: number;
}

// ── Strategies ────────────────────────────────────────────────────────────────

export interface Strategy {
  id: number;
  name: string;
  description: string | null;
  strategy_type: "config" | "prompt" | "code";
  trigger_type: "interval" | "candle_close";
  interval_minutes: number | null;
  symbols: string[];
  timeframe: string;
  lot_size: number | null;
  sl_pips: number | null;
  tp_pips: number | null;
  news_filter: boolean;
  custom_prompt: string | null;
  module_path: string | null;
  class_name: string | null;
  is_active: boolean;
  binding_count: number;
}

export interface StrategyBinding {
  id: number;
  account_id: number;
  strategy_id: number;
  is_active: boolean;
  account_name: string;
}

export interface CreateStrategyPayload {
  name: string;
  description?: string;
  strategy_type: "config" | "prompt" | "code";
  trigger_type: "interval" | "candle_close";
  interval_minutes?: number;
  symbols: string[];
  timeframe: string;
  lot_size?: number;
  sl_pips?: number;
  tp_pips?: number;
  news_filter?: boolean;
  custom_prompt?: string;
  module_path?: string;
  class_name?: string;
}

export interface StrategyRun {
  id: number;
  account_id: number;
  symbol: string;
  timeframe: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  reasoning: string;
  created_at: string;
}

// ── History ───────────────────────────────────────────────────────────────────

export interface HistoryDeal {
  ticket: number;
  order: number;
  time: number;
  time_msc: number;
  type: number;
  entry: number;
  position_id: number;
  volume: number;
  price: number;
  commission: number;
  swap: number;
  profit: number;
  symbol: string;
  comment: string | null;
}

export interface HistorySyncResult {
  imported: number;
  total_fetched: number;
}

// ── Pipeline Logs ─────────────────────────────────────────────────────────────

export interface PipelineStep {
  id: number;
  run_id: number;
  seq: number;
  step_name: string;
  status: "ok" | "skip" | "error";
  input_json: string | null;
  output_json: string | null;
  error: string | null;
  duration_ms: number;
}

export interface PipelineRunSummary {
  id: number;
  account_id: number;
  symbol: string;
  timeframe: string;
  status: "running" | "completed" | "hold" | "skipped" | "failed";
  final_action: "BUY" | "SELL" | "HOLD" | null;
  total_duration_ms: number | null;
  journal_id: number | null;
  trade_id: number | null;
  created_at: string;
}

export interface PipelineRunDetail {
  run: PipelineRunSummary;
  steps: PipelineStep[];
}

export interface PipelineRunCompleteData {
  run_id: number;
  symbol: string;
  timeframe: string;
  status: string;
  final_action: string | null;
  total_duration_ms: number;
  step_count: number;
}

// ── Backtest ──────────────────────────────────────────────────────────────────

export interface BacktestRunSummary {
  id: number;
  strategy_id: number;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_balance: number;
  spread_pips: number;
  execution_mode: string;
  status: "pending" | "running" | "completed" | "failed";
  progress_pct: number;
  error_message: string | null;
  total_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  max_drawdown_pct: number | null;
  recovery_factor: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  total_return_pct: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  max_consec_wins: number | null;
  max_consec_losses: number | null;
  created_at: string;
}

export interface BacktestTrade {
  id: number;
  run_id: number;
  symbol: string;
  direction: "BUY" | "SELL";
  entry_time: string;
  exit_time: string | null;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number;
  take_profit: number;
  volume: number;
  profit: number | null;
  exit_reason: "sl" | "tp" | "signal_reverse" | "end_of_data" | null;
  equity_after: number | null;
}

export interface BacktestEquityPoint {
  time: string;
  equity: number;
}

export interface BacktestMonthlyPnl {
  year: number;
  month: number;
  pnl: number;
  trade_count: number;
}

export interface BacktestRunRequest {
  strategy_id: number;
  symbol: string;
  timeframe?: string;
  start_date: string;
  end_date: string;
  initial_balance?: number;
  spread_pips?: number;
  execution_mode?: "close_price" | "intra_candle";
  max_llm_calls?: number;
  volume?: number;
  csv_upload_id?: string;
}
