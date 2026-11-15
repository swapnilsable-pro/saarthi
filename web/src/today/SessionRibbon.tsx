import type { Clock } from "../api";
import { Term } from "../ui";

const PHASE_TEXT: Record<string, string> = {
  closed: "Market closed",
  pre_market: "Pre-market",
  pre_open: "Pre-open auction",
  opening_range: "Opening range forming",
  entry_window: "Entry window",
  manage_only: "Manage open trades only",
  square_off: "Square-off",
  post_close: "Closed for the day",
};

function minutes(t: string) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

export function SessionRibbon({ clock, demo }: { clock: Clock; demo: boolean }) {
  const m = clock.marks;
  const now = clock.now.slice(11, 16);
  const phase = PHASE_TEXT[clock.phase] ?? clock.phase;

  if (!m) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-semibold">{phase}</span>
        <span className="text-muted">
          {clock.holiday ? `Holiday: ${clock.holiday}` : `${clock.weekday}, no session`}
          {clock.next_session && <> · next session <b className="text-text num">{clock.next_session}</b></>}
        </span>
      </div>
    );
  }

  const open = minutes(m.open), close = minutes(m.close);
  const pos = (t: string) => `${((minutes(t) - open) / (close - open)) * 100}%`;
  const nowPct = Math.max(0, Math.min(100, ((minutes(now) - open) / (close - open)) * 100));
  const segs = [
    { from: m.open, to: m.or_end, cls: "bg-faint/40", label: "OR" },
    { from: m.or_end, to: m.no_new_entries, cls: "bg-go/35", label: "entries" },
    { from: m.no_new_entries, to: m.square_off, cls: "bg-caution/35", label: "manage" },
    { from: m.square_off, to: m.close, cls: "bg-stop/35", label: "flat" },
  ];

  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="font-semibold">{phase}</span>
        <span className="text-muted num">{clock.weekday} {clock.now.slice(0, 10)} · {now} IST{demo && " (demo clock)"}</span>
        {clock.muhurat && <span className="text-caution">Muhurat session</span>}
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-panel-2" role="img"
        aria-label={`Session ${m.open} to ${m.close}; opening range until ${m.or_end}; no new entries after ${m.no_new_entries}; square-off ${m.square_off}`}>
        {segs.map((s) => (
          <div key={s.label} className={`absolute top-0 h-full ${s.cls}`} style={{ left: pos(s.from), width: `calc(${pos(s.to)} - ${pos(s.from)})` }} />
        ))}
        {clock.progress !== null && clock.progress > 0 && clock.progress < 1 && (
          <div className="absolute top-[-2px] h-[14px] w-[3px] rounded bg-text" style={{ left: `${nowPct}%` }} />
        )}
      </div>
      <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-muted num">
        <li><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-faint/60" />{m.open}–{m.or_end} <Term k="orb">opening range</Term></li>
        <li><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-go/60" />until {m.no_new_entries} entries</li>
        <li><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-caution/60" />until {m.square_off} manage only</li>
        <li><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-stop/60" />{m.square_off} <Term k="square_off">square-off</Term> · close {m.close}</li>
      </ul>
    </div>
  );
}
