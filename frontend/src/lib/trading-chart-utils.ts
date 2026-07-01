import type { BusinessDay, UTCTimestamp } from "lightweight-charts";
import type { OHLCVCandle } from "@/components/chart/trading-chart";

// ── Indicator config ─────────────────────────────────────────────────────────
export const EMA_CONFIG: Record<20 | 50 | 200, { color: string; lineWidth: 1 | 2 | 3 | 4 }> = {
  20: { color: "#f59e0b", lineWidth: 1 },
  50: { color: "#a855f7", lineWidth: 1 },
  200: { color: "#3b82f6", lineWidth: 2 },
};

export function calcEMA(data: OHLCVCandle[], period: number): { time: UTCTimestamp; value: number }[] {
  if (data.length < period) return [];
  const k = 2 / (period + 1);
  let ema = data.slice(0, period).reduce((s, c) => s + c.close, 0) / period;
  const result: { time: UTCTimestamp; value: number }[] = [
    { time: data[period - 1].time as UTCTimestamp, value: ema },
  ];
  for (let i = period; i < data.length; i++) {
    ema = data[i].close * k + ema * (1 - k);
    result.push({ time: data[i].time as UTCTimestamp, value: ema });
  }
  return result;
}

export function calcRSI(data: OHLCVCandle[], period = 14): { time: UTCTimestamp; value: number }[] {
  if (data.length < period + 1) return [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = data[i].close - data[i - 1].close;
    if (d > 0) avgGain += d;
    else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  const result: { time: UTCTimestamp; value: number }[] = [
    { time: data[period].time as UTCTimestamp, value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss) },
  ];
  for (let i = period + 1; i < data.length; i++) {
    const d = data[i].close - data[i - 1].close;
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    result.push({
      time: data[i].time as UTCTimestamp,
      value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss),
    });
  }
  return result;
}

// MT5 color convention
export const ENTRY_BUY_COLOR = "#3b82f6";
export const ENTRY_SELL_COLOR = "#ef4444";
export const TP_COLOR = "#22c55e";
export const SL_COLOR = "#ef4444";
export const PENDING_BUY_COLOR = "#93c5fd";
export const PENDING_SELL_COLOR = "#fca5a5";

export function getColors(isDark: boolean) {
  return isDark
    ? { bg: "#09090b", text: "#a1a1aa", grid: "#27272a", border: "#3f3f46" }
    : { bg: "#fafafa", text: "#71717a", grid: "#e4e4e7", border: "#d4d4d8" };
}

export function makeTimeFormatter(
  tz: string,
): (time: BusinessDay | UTCTimestamp) => string {
  return (ts) => {
    if (typeof ts !== "number") return "";
    return new Date(ts * 1000).toLocaleString("en-GB", {
      timeZone: tz,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  };
}

/** Format price distance as pips (forex) or points (metals/indices). */
export function fmtDist(from: number, to: number, sym: string): string {
  const diff = Math.abs(to - from);
  if (from >= 100) return `${diff.toFixed(2)} pts`;
  const pip = sym.includes("JPY") ? 0.01 : 0.0001;
  return `${Math.round(diff / pip)} pips`;
}
