import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineStyle, type IChartApi, type SeriesMarker, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar, Plan } from "../api";

/** IST wall-clock "YYYY-MM-DD HH:MM" as a UTC timestamp, so the chart's axis reads in IST. */
function ts(s: string): UTCTimestamp {
  const [d, t] = s.split(" ");
  const [y, m, day] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return (Date.UTC(y, m - 1, day, h, mi) / 1000) as UTCTimestamp;
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

export function IdeaChart({ bars, plan, day, breakoutAt, decidedAt, hindsight }: {
  bars: Bar[]; plan: Plan | null; day: string; breakoutAt: string; decidedAt: string; hindsight: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const text = cssVar("--muted"), line = cssVar("--line"), go = cssVar("--go"), stop = cssVar("--stop");
    const accent = cssVar("--accent"), faint = cssVar("--faint"), caution = cssVar("--caution");
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: line },
      rightPriceScale: { borderColor: line },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: go, downColor: stop, borderUpColor: go, borderDownColor: stop, wickUpColor: go, wickDownColor: stop,
      // Keep the plan's levels (target, stop, range) on screen even when price never reached them.
      autoscaleInfoProvider: (orig: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const r = orig();
        if (!r || !plan) return r;
        return { ...r, priceRange: {
          minValue: Math.min(r.priceRange.minValue, plan.stop, plan.range.low),
          maxValue: Math.max(r.priceRange.maxValue, plan.target, plan.range.high),
        } };
      },
    });
    series.setData(bars.map((b) => ({ time: ts(b.time), open: b.o, high: b.h, low: b.l, close: b.c })));

    if (plan) {
      const pl = (price: number, title: string, color: string, style = LineStyle.Solid, width: 1 | 2 = 1) =>
        series.createPriceLine({ price, title, color, lineStyle: style, lineWidth: width, axisLabelVisible: true });
      pl(plan.range.high, "OR high", faint, LineStyle.Dashed);
      pl(plan.range.low, "OR low", faint, LineStyle.Dashed);
      pl(plan.entry, "Entry", accent, LineStyle.Solid, 2);
      pl(plan.stop, "Stop", stop, LineStyle.Solid, 2);
      pl(plan.t1, "+1R", caution, LineStyle.Dotted);
      pl(plan.target, `Target ${plan.target_r}R`, go, LineStyle.Solid, 2);
    }
    const markers: SeriesMarker<UTCTimestamp>[] = [
      { time: ts(`${day} ${breakoutAt}`), position: "belowBar", color: accent, shape: "arrowUp", text: "breakout" },
    ];
    if (hindsight) markers.push({ time: ts(`${day} ${decidedAt.slice(11, 16)}`), position: "aboveBar", color: faint, shape: "arrowDown", text: "decided" });
    markers.sort((a, b) => a.time - b.time);
    createSeriesMarkers(series, markers.filter((m) => bars.some((b) => ts(b.time) === m.time)));
    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [bars, plan, day, breakoutAt, decidedAt, hindsight]);

  return <div ref={ref} className="h-[340px] w-full" role="img" aria-label="Five-minute price chart with opening range, entry, stop and target lines" />;
}
