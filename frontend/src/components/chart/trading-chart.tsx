"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type IPriceLine,
  type UTCTimestamp,
  type SeriesMarker,
} from "lightweight-charts";
import type { Position, PendingOrder, TradeMarker } from "@/types/trading";
import {
  EMA_CONFIG,
  calcEMA,
  calcRSI,
  ENTRY_BUY_COLOR,
  ENTRY_SELL_COLOR,
  TP_COLOR,
  SL_COLOR,
  PENDING_BUY_COLOR,
  PENDING_SELL_COLOR,
  getColors,
  makeTimeFormatter,
  fmtDist,
} from "@/lib/trading-chart-utils";

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
  emaActive?: (20 | 50 | 200)[];
  rsiActive?: boolean;
  tradeMarkers?: TradeMarker[];
  /** When set, chart scrolls to show this unix timestamp (seconds). Used by trade table row-click. */
  focusTime?: number;
}

export function TradingChart({
  candles,
  positions,
  pendingOrders,
  symbol,
  isDark = true,
  timezone,
  viewResetKey,
  emaActive = [],
  rsiActive = false,
  tradeMarkers,
  focusTime,
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const emaSeriesRef = useRef<Map<20 | 50 | 200, ISeriesApi<any>>>(new Map());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rsiSeriesRef = useRef<ISeriesApi<any> | null>(null);
   
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<UTCTimestamp> | null>(null);

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
      emaSeriesRef.current.clear();
      rsiSeriesRef.current = null;
      markersPluginRef.current = null;
    };
  }, [symbol]); // candles/isDark/timezone/emaActive/rsiActive intentionally excluded — handled by Effects 1b/3/4/5/6

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

  // ── Effect 5: manage EMA overlay series ────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || candles.length === 0) return;

    const sorted = [...candles].sort((a, b) => a.time - b.time);
    const active = new Set(emaActive);

    // Remove stale series
    for (const [p, s] of emaSeriesRef.current.entries()) {
      if (!active.has(p)) {
        chart.removeSeries(s);
        emaSeriesRef.current.delete(p);
      }
    }

    // Add missing series + update data
    for (const p of active) {
      if (!emaSeriesRef.current.has(p)) {
        const { color, lineWidth } = EMA_CONFIG[p];
        const s = chart.addSeries(LineSeries, {
          color,
          lineWidth,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          title: `EMA${p}`,
        });
        emaSeriesRef.current.set(p, s);
      }
      emaSeriesRef.current.get(p)!.setData(calcEMA(sorted, p));
    }
  }, [candles, emaActive]);

  // ── Effect 6: manage RSI pane (native pane index 1 = separate subplot) ──────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (!rsiActive) {
      if (rsiSeriesRef.current) {
        chart.removeSeries(rsiSeriesRef.current);
        rsiSeriesRef.current = null;
        // Remove the now-empty RSI pane
        if (chart.panes().length > 1) chart.removePane(1);
      }
      return;
    }

    if (!rsiSeriesRef.current) {
      // paneIndex=1 creates a true separate pane below the main chart
      const s = chart.addSeries(LineSeries, {
        color: "#06b6d4",
        lineWidth: 1 as const,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
        title: "RSI(14)",
      }, 1);
      s.createPriceLine({ price: 70, color: "#ef444480", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "OB" });
      s.createPriceLine({ price: 30, color: "#22c55e80", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "OS" });
      s.createPriceLine({ price: 50, color: "#71717a40", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      // RSI pane occupies ~25% of total chart height
      chart.panes()[1]?.setStretchFactor(0.35);
      rsiSeriesRef.current = s;
    }

    if (candles.length > 0) {
      const sorted = [...candles].sort((a, b) => a.time - b.time);
      rsiSeriesRef.current.setData(calcRSI(sorted));
    }
  }, [rsiActive, candles]);

  // ── Effect 7: trade markers (backtest replay) ──────────────────────────────
  // v5 API: createSeriesMarkers() factory from 'lightweight-charts'
  // Docs: frontend/node_modules/lightweight-charts/dist/typings.d.ts:274
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    if (markersPluginRef.current) {
      markersPluginRef.current.setMarkers([]);
    }

    if (!tradeMarkers || tradeMarkers.length === 0) return;

    const markers: SeriesMarker<UTCTimestamp>[] = tradeMarkers.flatMap(
      (t): SeriesMarker<UTCTimestamp>[] => {
        const isBuy = t.direction === "BUY";
        const isWin = (t.profit ?? 0) >= 0;

        const entry: SeriesMarker<UTCTimestamp> = {
          time: t.entry_time as UTCTimestamp,
          position: isBuy ? "belowBar" : "aboveBar",
          shape: isBuy ? "arrowUp" : "arrowDown",
          color: isBuy ? "#22c55e" : "#ef4444",
          text: isBuy ? "B" : "S",
          size: 1,
        };

        if (!t.exit_time) return [entry];

        const exit: SeriesMarker<UTCTimestamp> = {
          time: t.exit_time as UTCTimestamp,
          position: isBuy ? "aboveBar" : "belowBar",
          shape: "circle",
          color: isWin ? "#22c55e" : "#ef4444",
          text:
            t.exit_reason === "sl"
              ? "SL"
              : t.exit_reason?.startsWith("tp")
              ? "TP"
              : "X",
          size: 1,
        };

        return [entry, exit];
      },
    );

    // lightweight-charts requires markers sorted by time
    markers.sort((a, b) => (a.time as number) - (b.time as number));

    if (!markersPluginRef.current) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      markersPluginRef.current = createSeriesMarkers(series as any, markers);
    } else {
      markersPluginRef.current.setMarkers(markers);
    }
  }, [tradeMarkers]);

  // ── Effect 8: scroll to focusTime (trade table row-click) ─────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !focusTime) return;
    const ts = focusTime as UTCTimestamp;
    const coord = chart.timeScale().timeToCoordinate(ts);
    if (coord !== null) {
      const logicalRange = chart.timeScale().getVisibleLogicalRange();
      if (logicalRange) {
        const barIdx = chart.timeScale().coordinateToLogical(coord) ?? 0;
        const halfWindow = 20;
        chart.timeScale().setVisibleLogicalRange({
          from: barIdx - halfWindow,
          to: barIdx + halfWindow,
        });
      }
    }
  }, [focusTime]);

  return <div ref={containerRef} className="relative w-full h-full" />;
}
