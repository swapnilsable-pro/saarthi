import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineStyle, type SeriesMarker, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar, PaperTrade } from "../api";

function ts(s: string): UTCTimestamp {
  const [d, t] = s.split(" ");
  const [y, m, day] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return (Date.UTC(y, m - 1, day, h, mi) / 1000) as UTCTimestamp;
}
const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888";

/** A paper trade on its session: bars, the order's stop/target, and each fill as a marker. */
export function TradeChart({ bars, trade }: { bars: Bar[]; trade: PaperTrade }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !bars.length) return;
    const text = cssVar("--muted"), line = cssVar("--line"), go = cssVar("--go"), stop = cssVar("--stop");
    const accent = cssVar("--accent"), paperC = cssVar("--paper");
    const o = trade.order_spec;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: line },
      rightPriceScale: { borderColor: line },
    });
    const s = chart.addSeries(CandlestickSeries, {
      upColor: go, downColor: stop, borderUpColor: go, borderDownColor: stop, wickUpColor: go, wickDownColor: stop,
      autoscaleInfoProvider: (orig: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const r = orig();
        if (!r) return r;
        const lv = [o.stop, o.target, o.entry_price].filter((x): x is number => typeof x === "number");
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...lv), maxValue: Math.max(r.priceRange.maxValue, ...lv) } };
      },
    });
    s.setData(bars.map((b) => ({ time: ts(b.time), open: b.o, high: b.h, low: b.l, close: b.c })));
    if (o.entry_price) s.createPriceLine({ price: o.entry_price, title: o.entry_type, color: accent, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true });
    s.createPriceLine({ price: o.stop, title: "Stop", color: stop, lineStyle: LineStyle.Solid, lineWidth: 1, axisLabelVisible: true });
    if (o.target) s.createPriceLine({ price: o.target, title: "Target", color: go, lineStyle: LineStyle.Solid, lineWidth: 1, axisLabelVisible: true });
    const marks: SeriesMarker<UTCTimestamp>[] = (trade.fills ?? []).map((f) => ({
      time: ts(f.time), position: f.kind === "ENTRY" ? "belowBar" : "aboveBar",
      color: f.kind === "ENTRY" ? paperC : f.kind === "TARGET" ? go : f.kind.includes("STOP") ? stop : text,
      shape: f.kind === "ENTRY" ? "arrowUp" : "arrowDown",
      text: `${f.kind === "ENTRY" ? "Buy" : f.kind.replace("_", " ").toLowerCase()} ${f.price.toFixed(2)}`,
    }));
    marks.push({ time: ts(o.placed_at), position: "aboveBar", color: text, shape: "circle", text: "placed" });
    marks.sort((a, b) => a.time - b.time);
    createSeriesMarkers(s, marks.filter((m) => bars.some((b) => ts(b.time) === m.time)));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, trade]);
  return <div ref={ref} className="h-[280px] w-full" role="img" aria-label={`Chart of the ${trade.symbol} paper trade with its fills`} />;
}
