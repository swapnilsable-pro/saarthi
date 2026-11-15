import { createContext, useContext, type ReactNode } from "react";

export function Card({ title, right, children, className = "" }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-panel ${className}`}>
      {title !== undefined && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[13px] font-semibold tracking-wide text-muted uppercase">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES = {
  go: "bg-go-soft text-go",
  caution: "bg-caution-soft text-caution",
  stop: "bg-stop-soft text-stop",
  paper: "bg-paper-soft text-paper",
  accent: "bg-accent-soft text-accent",
  neutral: "bg-panel-2 text-muted",
} as const;

export function Pill({ tone = "neutral", children, title }: {
  tone?: keyof typeof TONES; children: ReactNode; title?: string;
}) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  );
}

/** Plain-English explanations shown on hover / focus (IMPLEMENTATION_PLAN.md §9 design language). */
export const GLOSSARY: Record<string, string> = {
  breakout_20d: "20-day breakout: closed above its highest close of the last 20 sessions.",
  oversold_bounce: "Oversold bounce: RSI was deeply oversold and the stock closed up off the low.",
  reclaim_ma20: "Reclaimed the 20-day average: closed back above its 20-day moving average.",
  oversold: "Oversold: 14-day RSI is very low; selling may be exhausted.",
  bull_flag: "Bull flag: a tight pause after a sharp rise.",
  delivery: "Delivery %: share of traded quantity actually taken into demat. High = real buying, not just intraday churn.",
  rsi: "RSI(14): momentum from 0 to 100. Above 70 is stretched, below 30 is oversold.",
  turnover: "Turnover: value traded in the session, in ₹ crore.",
  band: "Price band: the exchange's daily limit. A stop beyond it cannot fill.",
  asm: "ASM: NSE's additional surveillance measure. Stricter margins; often no intraday trading.",
  exposure: "Exposure ceiling: the most of your capital the regime tool suggests having in the market.",
  distribution: "Distribution day: the index fell on higher volume, a sign of institutional selling.",
  breadth: "Breadth: how many stocks are joining the index's move. Weak breadth = a narrow, fragile rally.",
  orb: "Opening range: the high and low of the first 15 minutes (09:15–09:30).",
  square_off: "Square-off: brokers close intraday (MIS) positions themselves near 15:20; Saarthi exits at 15:15.",
};

export function Term({ k, children }: { k: string; children: ReactNode }) {
  const tip = GLOSSARY[k];
  if (!tip) return <>{children}</>;
  return (
    <span tabIndex={0} title={tip} aria-label={`${typeof children === "string" ? children : k}: ${tip}`}
      className="cursor-help underline decoration-dotted decoration-faint underline-offset-2">
      {children}
    </span>
  );
}

export const SETUP_LABEL: Record<string, string> = {
  breakout_20d: "20D breakout",
  oversold_bounce: "Oversold bounce",
  reclaim_ma20: "Reclaim 20DMA",
  oversold: "Oversold",
  bull_flag: "Bull flag",
};

// ---------------------------------------------------------------- evidence drawer context
type OpenFn = (runId: string, label: string) => void;
export const EvidenceCtx = createContext<OpenFn>(() => {});
export const useEvidence = () => useContext(EvidenceCtx);

export function EvidenceLink({ runId, label, children }: { runId?: string | null; label: string; children?: ReactNode }) {
  const open = useEvidence();
  if (!runId) return null;
  return (
    <button type="button" onClick={() => open(runId, label)}
      className="inline-flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted hover:border-accent hover:text-accent"
      aria-label={`Open evidence: ${label}`}>
      {children ?? "evidence"}
      <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden><path d="M4 2h6v6M10 2 3 9" stroke="currentColor" strokeWidth="1.5" fill="none" /></svg>
    </button>
  );
}

export function Skeleton({ h = 80 }: { h?: number }) {
  return <div className="animate-pulse rounded-lg bg-panel-2" style={{ height: h }} />;
}
