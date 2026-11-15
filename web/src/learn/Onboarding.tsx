import { useEffect, useRef, useState } from "react";
import { onboarding } from "../prefs";

const STEPS = [
  { title: "Welcome to Saarthi", body: <>
    <p>Saarthi is a <b>practice cockpit</b> for the Indian stock market. It runs two open-source skill packs, nse-trader-skill and claude-trading-skills-india, and shows you exactly what they found and why.</p>
    <p className="mt-2"><b>It can never place a real order.</b> There is no broker connection. Every trade here is simulated.</p>
  </> },
  { title: "How a day works", body: <ol className="list-decimal space-y-1.5 pl-5">
    <li><b>Today</b>: the evening scan builds a watchlist; at 08:30 the pre-market brief reads the market's mood and the day's events.</li>
    <li><b>Ideas</b>: after the first 15 minutes, every breakout becomes an idea with an entry, stop, target, odds after costs and the best time to enter, then a verdict: TAKE, WATCH or SKIP.</li>
    <li><b>Paper Desk</b>: trade an idea with pretend money and watch it fill bar by bar, with real Indian charges.</li>
    <li><b>History, Performance, Replay</b>: see how every idea would have done, whether the odds were honest, and practise past days without knowing the ending.</li>
  </ol> },
  { title: "Read every number with its evidence", body: <>
    <p>Anything with an <span className="rounded border border-line px-1 font-mono text-[11px]">evidence ↗</span> button opens the exact tool run behind it: the command, the data it read and its raw output. Underlined words explain themselves when you hover over them.</p>
    <p className="mt-2">Start with <b>Demo data</b> (real tools on archived data, works offline), then switch to <b>Live data</b> to scan today's market.</p>
  </> },
];

export function Onboarding({ forceOpen, onClose }: { forceOpen: boolean; onClose: () => void }) {
  const [open, setOpen] = useState(() => forceOpen || !onboarding.seen());
  const [step, setStep] = useState(0);
  const [ack, setAck] = useState(onboarding.seen());
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (forceOpen) { setOpen(true); setStep(0); } }, [forceOpen]);
  useEffect(() => { btn.current?.focus(); }, [open, step]);
  if (!open) return null;
  const last = step === STEPS.length - 1;
  const finish = () => { onboarding.done(); setOpen(false); onClose(); };
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="onb-title">
      <div className="w-full max-w-lg rounded-2xl border border-line bg-panel p-6 shadow-2xl">
        <p className="text-xs text-faint">Step {step + 1} of {STEPS.length}</p>
        <h2 id="onb-title" className="mt-1 text-lg font-semibold">{STEPS[step].title}</h2>
        <div className="mt-3 text-sm leading-relaxed text-muted">{STEPS[step].body}</div>
        {last && (
          <label className="mt-4 flex items-start gap-2 rounded-lg bg-panel-2 p-3 text-sm">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 accent-[var(--accent)]" />
            <span>I understand this is <b>educational software for simulated trading</b>, not investment advice, and that most intraday traders lose money.</span>
          </label>
        )}
        <div className="mt-5 flex items-center justify-between">
          <button onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0} className="text-sm text-muted disabled:opacity-30">Back</button>
          <div className="flex gap-1.5">{STEPS.map((_, i) => <span key={i} className={`h-1.5 w-5 rounded-full ${i === step ? "bg-accent" : "bg-panel-2"}`} />)}</div>
          <button ref={btn} onClick={() => (last ? finish() : setStep((s) => s + 1))} disabled={last && !ack}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{last ? "Start" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
