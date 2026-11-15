import type { EventItem, Today } from "../api";
import { Card, EvidenceLink, Pill } from "../ui";

const IMPACT_TONE = { high: "stop", medium: "caution", low: "neutral" } as const;

function Row({ e }: { e: EventItem }) {
  return (
    <li className="flex items-start gap-3 py-2">
      <div className="w-[68px] shrink-0 text-xs text-muted num">
        <div className="font-medium text-text">{e.date.slice(5)}{e.end && e.end !== e.date ? `–${e.end.slice(5)}` : ""}</div>
        <div>{e.end && e.end !== e.date ? "window" : e.weekday}{e.time_ist ? ` · ${e.time_ist}` : ""}</div>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-snug">{e.title}{e.uncertain && <span className="text-faint"> (date unconfirmed)</span>}</p>
        {e.why && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{e.why}</p>}
      </div>
      <Pill tone={IMPACT_TONE[e.impact] ?? "neutral"}>{e.impact}</Pill>
    </li>
  );
}

export function EventsCard({ events }: { events: Today["events"] }) {
  const g = events.gate;
  return (
    <Card title="Event risk" right={<EvidenceLink runId={events.run_id} label="Event calendar (event-calendar/events.py)" />}>
      <div className={`rounded-lg p-3 text-sm ${g.blocked ? "bg-stop-soft text-stop" : "bg-panel-2 text-muted"}`}>
        <span className="font-semibold">{g.blocked ? "Event gate: blocked. " : "Event gate: clear. "}</span>{g.reason}
      </div>
      {events.holiday && <p className="mt-2 text-sm text-caution">Exchange holiday: {events.holiday}</p>}

      <p className="mt-4 text-xs font-medium tracking-wide text-faint uppercase">On {events.session_day}</p>
      {events.today.length ? (
        <ul className="divide-y divide-line">{events.today.map((e) => <Row key={e.title + e.date} e={e} />)}</ul>
      ) : <p className="py-2 text-sm text-muted">Nothing scheduled.</p>}

      {events.upcoming.length > 0 && (
        <>
          <p className="mt-3 text-xs font-medium tracking-wide text-faint uppercase">Next 7 days</p>
          <ul className="divide-y divide-line">{events.upcoming.slice(0, 6).map((e) => <Row key={e.title + e.date} e={e} />)}</ul>
        </>
      )}
    </Card>
  );
}
