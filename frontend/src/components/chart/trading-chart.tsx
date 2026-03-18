"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
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
}

// MT5 color convention
const ENTRY_BUY_COLOR = "#3b82f6"; // blue
const ENTRY_SELL_COLOR = "#ef4444"; // red
const TP_COLOR = "#22c55e"; // green
const SL_COLOR = "#ef4444"; // red
const PENDING_BUY_COLOR = "#93c5fd"; // light blue
const PENDING_SELL_COLOR = "#fca5a5"; // light red

export function TradingChart({
  candles,
  positions,
  pendingOrders,
  symbol,
}: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<ISeriesApi<any> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  // ── Effect 1: initialize chart + load candles ──────────────────────────────
  // Only runs when candles or symbol change — preserves zoom/pan on P&L updates
  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#09090b" },
        textColor: "#a1a1aa",
      },
      grid: {
        vertLines: { color: "#27272a" },
        horzLines: { color: "#27272a" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#3f3f46" },
      timeScale: {
        borderColor: "#3f3f46",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

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

    const sorted = [...candles]
      .sort((a, b) => a.time - b.time)
      .map((c) => ({ ...c, time: c.time as UTCTimestamp }));
    candleSeries.setData(sorted);

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      priceLinesRef.current = [];
    };
  }, [candles, symbol]);

  // ── Effect 2: update price lines without touching the viewport ─────────────
  // Runs whenever positions/orders change; chart zoom/pan is preserved
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    // Remove all existing price lines
    for (const pl of priceLinesRef.current) {
      series.removePriceLine(pl);
    }
    priceLinesRef.current = [];

    const lines: IPriceLine[] = [];

    // ── Open positions ────────────────────────────────────────────────────────
    for (const pos of positions) {
      if (pos.symbol !== symbol) continue;
      const isLong = pos.type === "buy";
      const pnlSign = pos.profit >= 0 ? "+" : "";
      const entryLabel = `${pos.type.toUpperCase()} ${pos.volume} ${pnlSign}${pos.profit.toFixed(2)} $`;

      lines.push(
        series.createPriceLine({
          price: pos.open_price,
          color: isLong ? ENTRY_BUY_COLOR : ENTRY_SELL_COLOR,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: entryLabel,
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
            title: `TP #${pos.ticket}`,
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
            title: `SL #${pos.ticket}`,
          }),
        );
      }
    }

    // ── Pending orders ────────────────────────────────────────────────────────
    for (const order of pendingOrders) {
      if (order.symbol !== symbol) continue;
      const isBuyType = order.type.startsWith("buy");
      const orderLabel = order.type.replace(/_/g, " ").toUpperCase();

      lines.push(
        series.createPriceLine({
          price: order.price,
          color: isBuyType ? PENDING_BUY_COLOR : PENDING_SELL_COLOR,
          lineWidth: 1,
          lineStyle: LineStyle.LargeDashed,
          axisLabelVisible: true,
          title: orderLabel,
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
            title: "TP",
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
            title: "SL",
          }),
        );
      }
    }

    priceLinesRef.current = lines;
  }, [positions, pendingOrders, symbol]);

  return <div ref={containerRef} className="w-full h-full" />;
}
