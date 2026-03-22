import type { AgentDef } from "./types";

// ── Market Analysis Pipeline ───────────────────────────────────────────────

export const marketAgents: AgentDef[] = [
  {
    id: "market_analysis",
    name: "1. Market Analysis",
    role: "Assess market conditions & trend",
    color: "blue",
    inputs: [
      { name: "symbol + timeframe", type: "input" },
      { name: "current_price", type: "input" },
      { name: "indicators (RSI, MACD…)", type: "input" },
      { name: "OHLCV — last 20 candles", type: "input" },
      { name: "context_tfs OHLCV", type: "optional", description: "Higher-timeframe candles" },
      { name: "open_positions", type: "input" },
      { name: "recent_signals", type: "input" },
      { name: "news_context", type: "optional", description: "Pre-formatted news string from News Gate" },
      {
        name: "rag_context",
        type: "shared",
        from: "RAG Context Builder",
        description: "8-section performance history: WR, signal reliability, lessons, blocked symbols",
      },
    ],
    outputs: [
      { name: "trend (bullish/bearish/ranging)", type: "output" },
      { name: "trend_strength (0–1)", type: "output" },
      { name: "key_support / key_resistance", type: "output" },
      { name: "volatility (low/medium/high)", type: "output" },
      { name: "context_notes", type: "output" },
    ],
  },
  {
    id: "chart_vision",
    name: "2. Chart Vision",
    role: "Identify visual price patterns",
    color: "purple",
    optional: true,
    inputs: [
      { name: "symbol + timeframe", type: "input" },
      { name: "chart_image (base64 PNG)", type: "input" },
      {
        name: "market_context",
        type: "shared",
        from: "Agent 1",
        description: "trend, support/resistance, volatility, notes",
      },
    ],
    outputs: [
      { name: "chart_pattern (e.g. head_shoulders)", type: "output" },
      { name: "pattern_direction (bullish/bearish)", type: "output" },
      { name: "chart_notes", type: "output" },
    ],
  },
  {
    id: "execution_decision",
    name: "3. Execution Decision",
    role: "Final trade execution decision",
    color: "green",
    inputs: [
      { name: "symbol + timeframe + current_price", type: "input" },
      { name: "open_positions + recent_signals", type: "input" },
      {
        name: "market_context",
        type: "shared",
        from: "Agent 1",
        description: "trend, strength, support/resistance, volatility, notes",
      },
      {
        name: "visual_pattern",
        type: "shared",
        from: "Agent 2 (opt.)",
        description: "chart_pattern, direction, chart_notes",
      },
    ],
    outputs: [
      { name: "action (BUY/SELL/HOLD/LIMIT/STOP)", type: "output" },
      { name: "entry price", type: "output" },
      { name: "stop_loss / take_profit", type: "output" },
      { name: "confidence (0–1)", type: "output" },
      { name: "rationale", type: "output" },
    ],
  },
];

// ── Position Maintenance Pipeline ──────────────────────────────────────────

export const maintenanceAgents: AgentDef[] = [
  {
    id: "technical",
    name: "1a. Technical Analysis",
    role: "Assess position's technical merit",
    color: "blue",
    inputs: [
      { name: "symbol + timeframe", type: "input" },
      { name: "OHLCV — last 20 candles", type: "input" },
      { name: "indicators", type: "input" },
      {
        name: "position state",
        type: "input",
        description: "ticket, direction, entry, SL, TP, PnL, volume",
      },
      { name: "strategy_params", type: "input", description: "sl_pips, tp_pips, risk_pct" },
      {
        name: "rag_context",
        type: "shared",
        from: "RAG Context Builder",
        description: "signal reliability, symbol WR, session patterns, lessons",
      },
    ],
    outputs: [
      { name: "trend + trend_strength", type: "output" },
      { name: "position_alignment", type: "output", description: "aligned | misaligned | neutral" },
      { name: "technical_score (–1 to 1)", type: "output" },
      { name: "notes", type: "output" },
    ],
  },
  {
    id: "sentiment",
    name: "1b. Sentiment Analysis",
    role: "Assess news sentiment for symbol",
    color: "amber",
    inputs: [
      { name: "symbol", type: "input" },
      { name: "news_context", type: "optional", description: "Upcoming events string" },
      {
        name: "rag_context",
        type: "shared",
        from: "RAG Context Builder",
        description: "signal reliability, symbol WR, session patterns, lessons",
      },
    ],
    outputs: [
      { name: "sentiment_direction (BULLISH/BEARISH/NEUTRAL)", type: "output" },
      { name: "event_risk (HIGH/MEDIUM/LOW)", type: "output" },
      { name: "key_events[]", type: "output" },
      { name: "sentiment_score (–1 to 1)", type: "output" },
      { name: "notes", type: "output" },
    ],
  },
  {
    id: "decision",
    name: "2. Maintenance Decision",
    role: "Final HOLD / CLOSE / MODIFY decision",
    color: "green",
    inputs: [
      { name: "symbol + position state", type: "input" },
      { name: "strategy_params", type: "input" },
      {
        name: "technical_output",
        type: "shared",
        from: "Agent 1a",
        description: "trend, alignment, technical_score, notes",
      },
      {
        name: "sentiment_output",
        type: "shared",
        from: "Agent 1b",
        description: "direction, event_risk, key_events, score",
      },
    ],
    outputs: [
      { name: "action (HOLD/CLOSE/MODIFY)", type: "output" },
      { name: "new_sl / new_tp", type: "output", description: "Only for MODIFY action" },
      { name: "confidence (0–1)", type: "output" },
      { name: "rationale", type: "output" },
    ],
  },
];

// ── News Pipelines ─────────────────────────────────────────────────────────

export const newsGateAgent: AgentDef = {
  id: "news_gate",
  name: "News Impact Gate",
  role: "Pre-execution gate — predict price direction from upcoming events",
  color: "rose",
  inputs: [
    { name: "symbol", type: "input" },
    {
      name: "upcoming_events[]",
      type: "input",
      description: "currency, title, forecast, previous, time",
    },
  ],
  outputs: [
    { name: "signal (BUY/SELL/HOLD)", type: "output" },
    { name: "reasoning", type: "output" },
  ],
};

export const economicEventAgent: AgentDef = {
  id: "econ_event",
  name: "Economic Event Analyst",
  role: "ForexFactory event pre-analysis (daily scheduler)",
  color: "purple",
  inputs: [
    { name: "event title + currency + impact", type: "input" },
    { name: "scheduled_time", type: "input" },
    { name: "forecast", type: "optional" },
    { name: "previous", type: "optional" },
    { name: "affected_symbols[]", type: "input" },
  ],
  outputs: [
    { name: "signal (BUY/SELL/HOLD/AVOID)", type: "output" },
    { name: "summary (2–3 sentences)", type: "output" },
    { name: "affected_symbols_detail", type: "output", description: "Per-symbol brief reason" },
  ],
};
