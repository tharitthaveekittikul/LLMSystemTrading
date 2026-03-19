"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
  type BusinessDay,
} from "lightweight-charts";
import type { Position, PendingOrder } from "@/types/trading";

export interface OHLCVCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface TradingChartProps {
  candles: OHLCVCandle[];
  positions: Position[];
  pendingOrders: PendingOrder[];
  symbol: string;
  isDark?: boolean;
  timezone?: string;
  /** Increment/change when symbol/timeframe/count changes to trigger fitContent.
   *  Auto-refresh should NOT change this — just update candles. */
  viewResetKey?: string;
}

// MT5 color convention
const ENTRY_BUY_COLOR = "#3b82f6";
const ENTRY_SELL_COLOR = "#ef4444";
const TP_COLOR = "#22c55e";
const SL_COLOR = "#ef4444";
const PENDING_BUY_COLOR = "#93c5fd";
const PENDING_SELL_COLOR = "#fca5a5";

function getColors(isDark: boolean) {
  return isDark
    ? { bg: "#09090b", text: "#a1a1aa", grid: "#27272a", border: "#3f3f46" }
    : { bg: "#fafafa", text: "#71717a", grid: "#e4e4e7", border: "#d4d4d8" };
}

function makeTimeFormatter(
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
function fmtDist(from: number, to: number, sym: string): string {
  const diff = Math.abs(to - from);
  if (from >= 100) return `${diff.toFixed(2)} pts`;
  const pip = sym.includes("JPY") ? 0.01 : 0.0001;
  return `${Math.round(diff / pip)} pips`;
}

export function TradingChart({
  candles,
  positions,
  pendingOrders,
  symbol,
  isDark = true,
  timezone,
  viewResetKey,
}: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<ISeriesApi<any> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volSeriesRef = useRef<ISeriesApi<any> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const legendRef = useRef<HTMLDivElement | null>(null);
  const prevViewResetKeyRef = useRef<string>("");

  // Keep latest prop values accessible inside effects without adding to deps.
  // Updated via useLayoutEffect (runs before useEffect) to avoid ref-in-render lint error.
  const isDarkRef = useRef(isDark);
  const timezoneRef = useRef(timezone);
  useLayoutEffect(() => {
    isDarkRef.current = isDark;
    timezoneRef.current = timezone;
  }, [isDark, timezone]);

  // ── Effect 1: initialize chart (only on symbol change) ────────────────────
  // Data is loaded by Effect 1b; theme/timezone by Effects 3 & 4.
  useEffect(() => {
    if (!containerRef.current) return;

    const colors = getColors(isDarkRef.current);
    const tz =
      timezoneRef.current ?? Intl.DateTimeFormat().resolvedOptions().timeZone;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: colors.bg },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: colors.border },
      timeScale: {
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
      },
      localization: {
        timeFormatter: makeTimeFormatter(tz),
      },
    });

    chartRef.current = chart;

    // ── Candlestick series ─────────────────────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    seriesRef.current = candleSeries;
    priceLinesRef.current = [];

    // ── Volume histogram (bottom 20% of chart, separate scale) ────────────────
    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    volSeriesRef.current = volSeries;

    // ── OHLCV crosshair legend (imperative DOM — avoids React re-renders) ──────
    const legend = document.createElement("div");
    legend.style.cssText =
      `position:absolute;top:8px;left:12px;z-index:10;` +
      `display:flex;gap:10px;font-size:11px;font-family:monospace;` +
      `color:${colors.text};pointer-events:none;user-select:none`;
    containerRef.current.appendChild(legend);
    legendRef.current = legend;

    const fmt = (v: number) =>
      v >= 100 ? v.toFixed(2) : v.toFixed(v >= 1 ? 4 : 5);

    chart.subscribeCrosshairMove((param) => {
      if (!param.point) {
        legend.innerHTML = "";
        return;
      }
      const bar = param.seriesData?.get(candleSeries) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      const vol = param.seriesData?.get(volSeries) as
        | { value: number }
        | undefined;
      if (!bar) {
        legend.innerHTML = "";
        return;
      }
      const c = bar.close >= bar.open ? "#22c55e" : "#ef4444";
      const t = getColors(isDarkRef.current).text;
      legend.innerHTML =
        `<span style="color:${t}">O&nbsp;<b style="color:${c}">${fmt(bar.open)}</b></span>` +
        `<span style="color:${t}">H&nbsp;<b style="color:${c}">${fmt(bar.high)}</b></span>` +
        `<span style="color:${t}">L&nbsp;<b style="color:${c}">${fmt(bar.low)}</b></span>` +
        `<span style="color:${t}">C&nbsp;<b style="color:${c}">${fmt(bar.close)}</b></span>` +
        (vol
          ? `<span style="color:${t}">V&nbsp;<b style="color:#a1a1aa">${vol.value.toLocaleString()}</b></span>`
          : "");
    });

    return () => {
      legend.remove();
      legendRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volSeriesRef.current = null;
      priceLinesRef.current = [];
      prevViewResetKeyRef.current = ""; // reset so next data load triggers fitContent
    };
  }, [symbol]); // candles/isDark/timezone intentionally excluded — handled by Effects 1b/3/4

  // ── Effect 1b: update candle + volume data (no chart recreation) ───────────
  // fitContent fires only when viewResetKey changes (symbol/tf/count change).
  // Auto-refresh updates candles without changing viewResetKey → viewport preserved.
  useEffect(() => {
    const series = seriesRef.current;
    const vol = volSeriesRef.current;
    if (!series || !vol || candles.length === 0) return;

    const sorted = [...candles]
      .sort((a, b) => a.time - b.time)
      .map((c) => ({ ...c, time: c.time as UTCTimestamp }));

    series.setData(sorted);
    vol.setData(
      sorted.map((c) => ({
        time: c.time,
        value: (c as OHLCVCandle).volume,
        color: c.close >= c.open ? "#22c55e30" : "#ef444430",
      })),
    );

    const key = viewResetKey ?? "";
    if (key !== prevViewResetKeyRef.current) {
      chartRef.current?.timeScale().fitContent();
      prevViewResetKeyRef.current = key;
    }
  }, [candles, viewResetKey]);

  // ── Effect 2: update price lines without touching the viewport ─────────────
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    for (const pl of priceLinesRef.current) series.removePriceLine(pl);
    priceLinesRef.current = [];

    const lines: IPriceLine[] = [];

    for (const pos of positions) {
      if (pos.symbol !== symbol) continue;
      const isLong = pos.type === "buy";
      const pnlSign = pos.profit >= 0 ? "+" : "";

      lines.push(
        series.createPriceLine({
          price: pos.open_price,
          color: isLong ? ENTRY_BUY_COLOR : ENTRY_SELL_COLOR,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `${pos.type.toUpperCase()} ${pos.volume} ${pnlSign}${pos.profit.toFixed(2)} USD`,
        }),
      );

      if (pos.tp && pos.tp > 0) {
        lines.push(
          series.createPriceLine({
            price: pos.tp,
            color: TP_COLOR,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `TP +${fmtDist(pos.open_price, pos.tp, symbol)} #${pos.ticket}`,
          }),
        );
      }

      if (pos.sl && pos.sl > 0) {
        lines.push(
          series.createPriceLine({
            price: pos.sl,
            color: SL_COLOR,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `SL \u2212${fmtDist(pos.open_price, pos.sl, symbol)} #${pos.ticket}`,
          }),
        );
      }
    }

    for (const order of pendingOrders) {
      if (order.symbol !== symbol) continue;
      const isBuyType = order.type.startsWith("buy");

      lines.push(
        series.createPriceLine({
          price: order.price,
          color: isBuyType ? PENDING_BUY_COLOR : PENDING_SELL_COLOR,
          lineWidth: 1,
          lineStyle: LineStyle.LargeDashed,
          axisLabelVisible: true,
          title: order.type.replace(/_/g, " ").toUpperCase(),
        }),
      );

      if (order.tp && order.tp > 0) {
        lines.push(
          series.createPriceLine({
            price: order.tp,
            color: "#86efac",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: false,
            title: `TP +${fmtDist(order.price, order.tp, symbol)}`,
          }),
        );
      }

      if (order.sl && order.sl > 0) {
        lines.push(
          series.createPriceLine({
            price: order.sl,
            color: "#fca5a5",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: false,
            title: `SL \u2212${fmtDist(order.price, order.sl, symbol)}`,
          }),
        );
      }
    }

    priceLinesRef.current = lines;
  }, [positions, pendingOrders, symbol]);

  // ── Effect 3: apply theme change without recreating the chart ──────────────
  useEffect(() => {
    if (!chartRef.current) return;
    const colors = getColors(isDark);
    chartRef.current.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: colors.bg },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border },
    });
    if (legendRef.current) legendRef.current.style.color = colors.text;
  }, [isDark]);

  // ── Effect 4: apply timezone change without recreating the chart ───────────
  useEffect(() => {
    if (!chartRef.current) return;
    const tz = timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    chartRef.current.applyOptions({
      localization: { timeFormatter: makeTimeFormatter(tz) },
    });
  }, [timezone]);

  return <div ref={containerRef} className="relative w-full h-full" />;
}
