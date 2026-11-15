import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineStyle, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { DailyBar } from "../api";

const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888";

/** Daily candles with plan levels and dated markers (decision day, fills). */
export function DailyChart({ bars, levels, marks, height = 320 }: {
  bars: DailyBar[];
  levels: { price: number; title: string; tone: "entry" | "stop" | "target" | "muted" }[];
  marks: { date: string; text: string; tone: "entry" | "exit" | "muted"; above?: boolean }[];
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !bars.length) return;
    const text = cssVar("--muted"), line = cssVar("--line"), go = cssVar("--go"), stop = cssVar("--stop");
    const c = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      timeScale: { borderColor: line }, rightPriceScale: { borderColor: line },
    });
    const s = c.addSeries(CandlestickSeries, {
      upColor: go, downColor: stop, borderUpColor: go, borderDownColor: stop, wickUpColor: go, wickDownColor: stop,
      autoscaleInfoProvider: (orig: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const r = orig();
        if (!r || !levels.length) return r;
        const p = levels.map((l) => l.price);
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...p), maxValue: Math.max(r.priceRange.maxValue, ...p) } };
      },
    });
    s.setData(bars.map((b) => ({ time: b.date as Time, open: b.o, high: b.h, low: b.l, close: b.c })));
    const col = { entry: cssVar("--accent"), stop, target: go, muted: cssVar("--faint") };
    levels.forEach((l) => s.createPriceLine({ price: l.price, title: l.title, color: col[l.tone], lineWidth: 1,
      lineStyle: l.tone === "entry" || l.tone === "muted" ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true }));
    const have = new Set(bars.map((b) => b.date));
    const mk: SeriesMarker<Time>[] = marks.filter((m) => have.has(m.date)).sort((a, b) => a.date.localeCompare(b.date)).map((m) => ({
      time: m.date as Time, position: m.above ? "aboveBar" : "belowBar",
      color: m.tone === "entry" ? cssVar("--paper") : m.tone === "exit" ? cssVar("--caution") : text,
      shape: m.tone === "muted" ? "circle" : m.above ? "arrowDown" : "arrowUp", text: m.text,
    }));
    createSeriesMarkers(s, mk);
    // Open on the last ~100 sessions (the base and what followed); the full history is a scroll away.
    if (bars.length > 110) c.timeScale().setVisibleLogicalRange({ from: bars.length - 100, to: bars.length + 2 });
    else c.timeScale().fitContent();
    return () => c.remove();
  }, [bars, levels, marks]);
  return <div ref={ref} style={{ height }} className="w-full" role="img" aria-label="Daily price chart with the swing plan" />;
}
