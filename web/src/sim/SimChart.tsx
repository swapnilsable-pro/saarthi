import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar, SimTrade } from "../api";

function ts(s: string): UTCTimestamp {
  const [d, t] = s.split(" ");
  const [y, m, day] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return (Date.UTC(y, m - 1, day, h, mi) / 1000) as UTCTimestamp;
}
const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888";

/** Live-updating replay chart: the chart is created once; each clock tick only appends bars
 *  (series.setData on the same series), so playback does not flicker or reset the zoom. */
export function SimChart({ bars, levels, trades }: {
  bars: Bar[]; levels: { price: number; title: string; tone: "entry" | "stop" | "target" }[]; trades: SimTrade[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);

  useEffect(() => {
    if (!ref.current) return;
    const text = cssVar("--muted"), line = cssVar("--line"), go = cssVar("--go"), stop = cssVar("--stop");
    const c = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: line, rightOffset: 6 },
      rightPriceScale: { borderColor: line },
    });
    series.current = c.addSeries(CandlestickSeries, { upColor: go, downColor: stop, borderUpColor: go, borderDownColor: stop, wickUpColor: go, wickDownColor: stop });
    markers.current = createSeriesMarkers(series.current, []);
    chart.current = c;
    return () => { c.remove(); chart.current = null; series.current = null; };
  }, []);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    s.setData(bars.map((b) => ({ time: ts(b.time), open: b.o, high: b.h, low: b.l, close: b.c })));
    // A session is at most 75 bars: always show all of it, so the day keeps its shape as it grows.
    if (bars.length) chart.current?.timeScale().fitContent();

    lines.current.forEach((l) => s.removePriceLine(l));
    const col = { entry: cssVar("--accent"), stop: cssVar("--stop"), target: cssVar("--go") };
    lines.current = levels.map((l) => s.createPriceLine({ price: l.price, title: l.title, color: col[l.tone], lineStyle: l.tone === "entry" ? LineStyle.Dashed : LineStyle.Solid, lineWidth: 1, axisLabelVisible: true }));

    const have = new Set(bars.map((b) => b.time));
    const m: SeriesMarker<Time>[] = trades.flatMap((t) => {
      const out: SeriesMarker<Time>[] = [];
      if (t.entry_at && have.has(t.entry_at)) out.push({ time: ts(t.entry_at), position: "belowBar", color: cssVar("--paper"), shape: "arrowUp", text: `Buy ${t.entry_price?.toFixed(2)}` });
      if (t.exit_at && have.has(t.exit_at)) out.push({ time: ts(t.exit_at), position: "aboveBar", color: (t.net_pnl ?? 0) >= 0 ? cssVar("--go") : cssVar("--stop"), shape: "arrowDown", text: `Sell ${t.exit_price?.toFixed(2)}` });
      return out;
    }).sort((a, b) => (a.time as number) - (b.time as number));
    markers.current?.setMarkers(m);
  }, [bars, levels, trades]);

  return <div ref={ref} className="h-[360px] w-full" role="img" aria-label="Replay chart: bars up to the simulated clock" />;
}
