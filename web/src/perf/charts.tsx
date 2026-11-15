/* Small SVG charts following the dataviz method: one axis, thin marks (2px lines, 4px rounded
   bar ends, >=8px dots), recessive grid, a hover tooltip on every chart, and a table view.
   P&L polarity uses the validated diverging pair (--viz-pos / --viz-neg). */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { inr } from "../api";

export const money = (v: number) => `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(Math.round(v)))}`;

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceTicks(lo: number, hi: number, n = 4): number[] {
  if (lo === hi) { lo -= 1; hi += 1; }
  const step0 = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? step0;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}

export function Tooltip({ x, y, w, children }: { x: number; y: number; w: number; children: ReactNode }) {
  const left = Math.min(Math.max(x + 12, 4), w - 196);
  return (
    <div className="pointer-events-none absolute z-10 w-[190px] rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs shadow-lg"
      style={{ left, top: Math.max(0, y - 10) }} role="status">
      {children}
    </div>
  );
}

/** Frame: title, optional legend, and a Chart/Table switch (the table view is the accessible twin). */
export function ChartFrame({ title, subtitle, legend, table, children }: {
  title: ReactNode; subtitle?: ReactNode; legend?: ReactNode; table: ReactNode; children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="rounded-xl border border-line bg-panel">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-2.5">
        <div>
          <h2 className="text-[13px] font-semibold tracking-wide text-muted uppercase">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-faint">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-3">
          {legend}
          <div className="flex rounded-md bg-panel-2 p-0.5 text-[11px]" role="radiogroup" aria-label="View as">
            {["Chart", "Table"].map((v) => (
              <button key={v} role="radio" aria-checked={(v === "Table") === asTable} onClick={() => setAsTable(v === "Table")}
                className={`rounded px-2 py-0.5 ${(v === "Table") === asTable ? "bg-panel shadow-sm" : "text-muted"}`}>{v}</button>
            ))}
          </div>
        </div>
      </header>
      <div className="p-4">{asTable ? <div className="max-h-[320px] overflow-auto">{table}</div> : children}</div>
    </section>
  );
}

export function Legend({ items }: { items: { label: string; swatch: ReactNode }[] }) {
  return (
    <ul className="flex flex-wrap gap-3 text-[11px] text-muted">
      {items.map((i) => <li key={i.label} className="flex items-center gap-1.5">{i.swatch}{i.label}</li>)}
    </ul>
  );
}
export const Swatch = ({ color, line }: { color: string; line?: boolean }) =>
  line ? <span className="inline-block h-[2px] w-4 rounded" style={{ background: color }} />
    : <span className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: color }} />;

// ------------------------------------------------------------------------- equity curve (line)
export function EquityCurve({ points }: { points: { t: string; equity: number; symbol: string; net: number }[] }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 220, m = { l: 64, r: 12, t: 12, b: 26 };
  const data = [{ t: "start", equity: 0, symbol: "", net: 0 }, ...points];
  const ys = data.map((d) => d.equity);
  const ticks = niceTicks(Math.min(0, ...ys), Math.max(0, ...ys));
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const x = (i: number) => m.l + (i / Math.max(1, data.length - 1)) * (W - m.l - m.r);
  const y = (v: number) => m.t + (1 - (v - lo) / (hi - lo || 1)) * (H - m.t - m.b);
  const path = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.equity).toFixed(1)}`).join("");
  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  };
  const h = hover !== null ? data[hover] : null;
  return (
    <div ref={ref} className="relative">
      <svg width={W} height={H} role="img" aria-label={`Cumulative net P&L over ${points.length} trades, ending ${money(ys[ys.length - 1])}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--viz-ref)" : "var(--viz-grid)"} strokeWidth={1} />
            <text x={m.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--faint)">{money(t)}</text>
          </g>
        ))}
        <text x={m.l} y={H - 6} fontSize={11} fill="var(--faint)">trade 1</text>
        <text x={W - m.r} y={H - 6} textAnchor="end" fontSize={11} fill="var(--faint)">trade {points.length}</text>
        <path d={path} fill="none" stroke="var(--viz-line)" strokeWidth={2} strokeLinejoin="round" />
        {h && hover !== null && <>
          <line x1={x(hover)} x2={x(hover)} y1={m.t} y2={H - m.b} stroke="var(--viz-ref)" strokeDasharray="3 3" />
          <circle cx={x(hover)} cy={y(h.equity)} r={4.5} fill="var(--viz-line)" stroke="var(--panel)" strokeWidth={2} />
        </>}
        <rect x={m.l} y={m.t} width={W - m.l - m.r} height={H - m.t - m.b} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {h && hover !== null && hover > 0 && (
        <Tooltip x={x(hover)} y={y(h.equity)} w={W}>
          <p className="font-medium">Trade {hover} · {h.symbol}</p>
          <p className="text-muted">{h.t}</p>
          <p className="num">This trade <b>{money(h.net)}</b></p>
          <p className="num">Cumulative <b>{money(h.equity)}</b></p>
        </Tooltip>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------- R histogram (bars)
export function RHistogram({ bins }: { bins: { from: number | null; to: number | null; n: number }[] }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 180, m = { l: 28, r: 8, t: 10, b: 30 };
  const max = Math.max(1, ...bins.map((b) => b.n));
  const bw = (W - m.l - m.r) / bins.length;
  const label = (b: { from: number | null; to: number | null }) =>
    b.from === null ? `< ${b.to}R` : b.to === null ? `≥ ${b.from}R` : `${b.from} to ${b.to}R`;
  return (
    <div ref={ref} className="relative">
      <svg width={W} height={H} role="img" aria-label="Distribution of trade results in R">
        {niceTicks(0, max, 3).map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={m.t + (1 - t / max) * (H - m.t - m.b)} y2={m.t + (1 - t / max) * (H - m.t - m.b)} stroke="var(--viz-grid)" />
            <text x={m.l - 6} y={m.t + (1 - t / max) * (H - m.t - m.b) + 4} textAnchor="end" fontSize={11} fill="var(--faint)">{t}</text>
          </g>
        ))}
        {bins.map((b, i) => {
          const h = (b.n / max) * (H - m.t - m.b);
          const neg = (b.to ?? 1) <= 0;
          const bx = m.l + i * bw + 1, w = Math.max(1, bw - 2);               // 2px surface gap between bars
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={m.l + i * bw} y={m.t} width={bw} height={H - m.t - m.b} fill="transparent" />
              {b.n > 0 && <path d={`M${bx},${H - m.b} v${-(h - 4)} q0,-4 4,-4 h${w - 8} q4,0 4,4 v${h - 4} z`}
                fill={neg ? "var(--viz-neg)" : "var(--viz-pos)"} opacity={hover === null || hover === i ? 1 : 0.55} />}
              {(i % 2 === 0 || bins.length < 8) && <text x={bx + w / 2} y={H - 12} textAnchor="middle" fontSize={10} fill="var(--faint)">
                {b.from === null ? `<${b.to}` : b.from}</text>}
            </g>
          );
        })}
        <text x={W - m.r} y={H - 1} textAnchor="end" fontSize={10} fill="var(--faint)">R (net of costs)</text>
      </svg>
      {hover !== null && (
        <Tooltip x={m.l + hover * bw} y={20} w={W}><p className="font-medium">{label(bins[hover])}</p><p className="num">{bins[hover].n} trade{bins[hover].n === 1 ? "" : "s"}</p></Tooltip>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------- calibration
export function CalibrationChart({ buckets, n }: {
  buckets: { from: number; to: number; n: number; predicted: number; observed: number }[]; n: number;
}) {
  const [ref, W0] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const W = Math.min(W0, 460), H = Math.min(W, 320), m = { l: 40, r: 22, t: 12, b: 34 };
  const x = (p: number) => m.l + p * (W - m.l - m.r);
  const y = (p: number) => m.t + (1 - p) * (H - m.t - m.b);
  const maxN = Math.max(1, ...buckets.map((b) => b.n));
  return (
    <div ref={ref} className="relative">
      <svg width={W} height={H} role="img" aria-label={`Calibration: predicted versus observed target hit rate across ${n} ghost trades`}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" />
            <line x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} stroke="var(--viz-grid)" />
            <text x={x(0) - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--faint)">{t * 100}%</text>
            <text x={x(t)} y={H - 18} textAnchor="middle" fontSize={11} fill="var(--faint)">{t * 100}%</text>
          </g>
        ))}
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--viz-ref)" strokeDasharray="4 4" />
        <text x={x(0.98)} y={y(0.98) + 14} textAnchor="end" fontSize={10} fill="var(--faint)">perfectly honest</text>
        <text x={(x(0) + x(1)) / 2} y={H - 2} textAnchor="middle" fontSize={11} fill="var(--muted)">Time Machine said: P(target first)</text>
        {buckets.map((b, i) => {
          const se = Math.sqrt(Math.max(b.observed * (1 - b.observed), 0.0025) / b.n);
          const lo = Math.max(0, b.observed - 1.96 * se), hi = Math.min(1, b.observed + 1.96 * se);
          const r = 4 + 6 * Math.sqrt(b.n / maxN);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <line x1={x(b.predicted)} x2={x(b.predicted)} y1={y(lo)} y2={y(hi)} stroke="var(--viz-line)" strokeWidth={2} opacity={0.45} />
              <circle cx={x(b.predicted)} cy={y(b.observed)} r={r} fill="var(--viz-line)" stroke="var(--panel)" strokeWidth={2} />
              <circle cx={x(b.predicted)} cy={y(b.observed)} r={r + 8} fill="transparent" />
            </g>
          );
        })}
      </svg>
      <p className="-mt-1 text-[11px] text-muted" style={{ marginLeft: 0 }}>Vertical axis: how often the target actually came first. Dot size = trades; whiskers = 95% range.</p>
      {hover !== null && (() => {
        const b = buckets[hover];
        return <Tooltip x={x(b.predicted)} y={y(b.observed)} w={W}>
          <p className="font-medium">Predicted {Math.round(b.from * 100)}–{Math.round(b.to * 100)}%</p>
          <p className="num">Average prediction {(b.predicted * 100).toFixed(0)}%</p>
          <p className="num">Actually hit <b>{(b.observed * 100).toFixed(0)}%</b> of {b.n}</p>
        </Tooltip>;
      })()}
    </div>
  );
}

// ------------------------------------------------------------------------- diverging horizontal bars
export function DivergingBars({ rows }: { rows: { key: string; label: ReactNode; value: number; note?: ReactNode }[] }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  return (
    <ul className="space-y-2">
      {rows.map((r) => {
        const w = (Math.abs(r.value) / max) * 50;
        return (
          <li key={r.key} className="grid grid-cols-[minmax(120px,200px)_1fr_90px] items-center gap-3 text-sm" title={`${r.key}: ${money(r.value)}`}>
            <span className="truncate">{r.label}</span>
            <div className="relative h-4">
              <div className="absolute inset-y-0 left-1/2 w-px bg-[var(--viz-ref)]" />
              <div className="absolute inset-y-[3px] rounded-[4px]"
                style={r.value >= 0 ? { left: "50%", width: `${w}%`, background: "var(--viz-pos)" } : { right: "50%", width: `${w}%`, background: "var(--viz-neg)" }} />
            </div>
            <span className="text-right num">{money(r.value)}{r.note && <span className="block text-[11px] text-faint">{r.note}</span>}</span>
          </li>
        );
      })}
    </ul>
  );
}
