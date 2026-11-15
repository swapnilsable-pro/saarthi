import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { perfApi, type HistoryDay, type Mode } from "../api";
import { VERDICT_CLS, VERDICT_ICON } from "../ideas/IdeaDetail";
import { Card, Pill, Skeleton } from "../ui";
import { Legend, money, Swatch } from "./charts";

type Lens = "all_ghost_net" | "take_ghost_net" | "my_net";
const LENS: Record<Lens, string> = {
  my_net: "Your paper trades",
  take_ghost_net: "Every TAKE, as planned",
  all_ghost_net: "Every idea, as planned",
};

export function ReplayCard({ mode }: { mode: Mode }) {
  const qc = useQueryClient();
  const [last, setLast] = useState(30);
  const run = useMutation({
    mutationFn: () => perfApi.replay(mode, last),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <section className="rounded-xl border border-line bg-panel p-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div className="min-w-[260px] flex-1">
          <h2 className="text-base font-semibold">Replay past sessions</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Re-runs each past session exactly as the live scheduler would have: brief at 08:30, a decision when each breakout's bar
            closes (tools told it is that moment, so they see nothing later), then every idea traded as planned in a separate
            <b> ghost</b> book. {mode === "demo" && "Demo: the nse repo's synthetic DEMO instrument, Sep–Nov 2026."}
          </p>
        </div>
        <label className="text-xs text-muted">Sessions
          <select value={last} onChange={(e) => setLast(Number(e.target.value))} className="mt-1 block h-9 rounded-md border border-line bg-panel px-2 text-sm text-text">
            {[10, 20, 30, 40].map((n) => <option key={n} value={n}>last {n}</option>)}
          </select>
        </label>
        <button onClick={() => run.mutate()} disabled={run.isPending} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60">
          {run.isPending ? "Replaying… (about 1 s a session)" : "Replay"}
        </button>
      </div>
      {run.data && (run.data.error ? <p className="mt-3 text-sm text-stop">{run.data.error}</p> :
        <p className="mt-3 rounded-lg bg-panel-2 p-3 text-sm">
          Replayed <b>{run.data.days}</b> sessions ({run.data.from} to {run.data.to}) in {run.data.seconds}s:{" "}
          <b>{run.data.ideas}</b> new ideas {Object.entries(run.data.by_verdict).map(([k, v]) => `${v} ${k}`).join(", ")}
          {run.data.ideas === 0 && " (already replayed)"}, {run.data.ghosts} ghost trades.
        </p>)}
    </section>
  );
}

export function HistoryPage({ mode, openIdea }: { mode: Mode; openIdea: (id: string) => void }) {
  const h = useQuery({ queryKey: ["history", mode], queryFn: () => perfApi.history(mode) });
  const [lens, setLens] = useState<Lens>("all_ghost_net");
  const [day, setDay] = useState<string | null>(null);
  const days = h.data?.days ?? [];
  const sel = day ?? [...days].reverse().find((d) => d.ideas)?.day ?? null;

  return (
    <div className="space-y-4">
      <ReplayCard mode={mode} />
      {h.isLoading ? <Skeleton h={240} /> : days.length === 0 ? (
        <Card><p className="py-8 text-center text-sm text-muted">No sessions yet. Replay past sessions above, or let the scheduler run live.</p></Card>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Card title="Decision calendar" right={
            <select value={lens} onChange={(e) => setLens(e.target.value as Lens)} aria-label="Colour days by"
              className="h-7 rounded-md border border-line bg-panel px-1.5 text-xs">
              {(Object.keys(LENS) as Lens[]).map((k) => <option key={k} value={k}>{LENS[k]}</option>)}
            </select>}>
            <Calendar days={days} lens={lens} selected={sel} onPick={setDay} />
          </Card>
          {sel && <DayPanel mode={mode} day={sel} openIdea={openIdea} />}
        </div>
      )}
    </div>
  );
}

function Calendar({ days, lens, selected, onPick }: { days: HistoryDay[]; lens: Lens; selected: string | null; onPick: (d: string) => void }) {
  const byDay = useMemo(() => Object.fromEntries(days.map((d) => [d.day, d])), [days]);
  const max = Math.max(1, ...days.map((d) => Math.abs(d[lens])));
  const months = useMemo(() => {
    const set = [...new Set(days.map((d) => d.day.slice(0, 7)))].sort();
    return set.map((ym) => {
      const [y, m] = ym.split("-").map(Number);
      const first = new Date(Date.UTC(y, m - 1, 1));
      const n = new Date(Date.UTC(y, m, 0)).getUTCDate();
      const lead = (first.getUTCDay() + 6) % 7;     // Monday-first
      return { ym, label: first.toLocaleString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" }), lead, n };
    });
  }, [days]);
  const fill = (v: number, has: boolean) => {
    if (!has) return "transparent";
    if (Math.abs(v) < 0.5) return "var(--viz-mid)";
    const pct = Math.round(25 + 75 * Math.min(1, Math.abs(v) / max));
    return `color-mix(in oklab, ${v > 0 ? "var(--viz-pos)" : "var(--viz-neg)"} ${pct}%, var(--viz-mid))`;
  };
  return (
    <div>
      <Legend items={[
        { label: "loss", swatch: <Swatch color="var(--viz-neg)" /> },
        { label: "flat / no trade", swatch: <Swatch color="var(--viz-mid)" /> },
        { label: "gain", swatch: <Swatch color="var(--viz-pos)" /> },
      ]} />
      <div className="mt-3 flex flex-wrap gap-6">
        {months.map((mo) => (
          <div key={mo.ym}>
            <p className="mb-1.5 text-xs font-medium text-muted">{mo.label}</p>
            <div className="grid grid-cols-7 gap-[3px] text-[10px]" role="grid" aria-label={mo.label}>
              {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <span key={i} className="text-center text-faint">{d}</span>)}
              {Array.from({ length: mo.lead }, (_, i) => <span key={`l${i}`} />)}
              {Array.from({ length: mo.n }, (_, i) => {
                const dd = `${mo.ym}-${String(i + 1).padStart(2, "0")}`;
                const rec = byDay[dd];
                const v = rec ? rec[lens] : 0;
                return (
                  <button key={dd} disabled={!rec} onClick={() => rec && onPick(dd)} role="gridcell"
                    title={rec ? `${dd}: ${rec.ideas} idea(s) · ${money(v)}` : dd}
                    aria-label={rec ? `${dd}, ${rec.ideas} ideas, ${money(v)}` : `${dd}, no session`}
                    className={`relative flex h-8 w-8 items-center justify-center rounded-[5px] border num ${selected === dd ? "border-text" : rec ? "border-line" : "border-transparent"} ${rec ? "cursor-pointer" : "text-faint/50"}`}
                    style={{ background: fill(v, !!rec) }}>
                    <span className={rec && Math.abs(v) / max > 0.6 ? "text-white" : ""}>{i + 1}</span>
                    {rec && rec.ideas > 0 && <span className="absolute bottom-[2px] h-1 w-1 rounded-full bg-text/70" />}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-faint">Dot = at least one idea that day. Ghost books are hindsight: what would have happened, never seen by a decision.</p>
    </div>
  );
}

function DayPanel({ mode, day, openIdea }: { mode: Mode; day: string; openIdea: (id: string) => void }) {
  const q = useQuery({ queryKey: ["day", mode, day], queryFn: () => perfApi.day(mode, day) });
  const [showGhost, setShowGhost] = useState(true);
  const d = q.data;
  return (
    <Card title={<>Session {day} <span className="font-normal normal-case text-faint">· {new Date(day + "T00:00:00Z").toLocaleDateString("en-IN", { weekday: "long", timeZone: "UTC" })}</span></>}
      right={<label className="flex items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={showGhost} onChange={(e) => setShowGhost(e.target.checked)} className="accent-[var(--accent)]" />ghost outcomes</label>}>
      {!d ? <Skeleton h={200} /> : (
        <div className="space-y-4">
          <ol className="relative ml-2 space-y-2 border-l border-line pl-4">
            {d.events.map((e, i) => (
              <li key={i} className="relative text-sm">
                <span className={`absolute -left-[21px] top-1.5 h-2 w-2 rounded-full ${e.kind === "idea" ? "bg-accent" : e.kind === "fill" ? "bg-paper" : "bg-faint"}`} />
                <span className="mr-2 text-xs text-faint num">{e.time}</span>{e.text}
              </li>
            ))}
          </ol>
          {d.ideas.map((i) => {
            const vc = VERDICT_CLS[i.verdict];
            const g = i.ghost;
            return (
              <button key={i.id} onClick={() => openIdea(i.id)} className="block w-full rounded-lg border border-line p-3 text-left hover:border-accent">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{i.symbol} <span className="text-xs font-normal text-faint num">{i.decided_at}</span></span>
                  <span className={`rounded-md px-2 py-0.5 text-xs font-bold ${vc.soft} ${vc.text}`}>{VERDICT_ICON[i.verdict]} {i.verdict}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-muted">{i.reason}</p>
                <p className="mt-1 text-xs num">Predicted: target first {i.p_target !== null ? `${Math.round(i.p_target * 100)}%` : "–"}, {i.pred_net !== null ? money(i.pred_net) : "–"}/trade</p>
                {showGhost && g && (
                  <p className="mt-1 text-xs num">
                    <Pill tone="neutral">hindsight</Pill>{" "}
                    {g.status === "closed" ? <>Traded as planned: {g.exit_reason?.toLowerCase().replace("_", " ")} → <b>{money(g.net_pnl ?? 0)}</b> ({g.r_multiple?.toFixed(2)}R)</>
                      : `Entry never filled (${g.status})`}
                  </p>
                )}
              </button>
            );
          })}
          {d.my_trades.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">Your paper trades</p>
              {d.my_trades.map((t) => <p key={t.id} className="text-sm num">{t.symbol}: {t.status} {t.exit_reason ? `· ${t.exit_reason.toLowerCase()}` : ""} {t.net_pnl !== null && <b>{money(t.net_pnl)}</b>}</p>)}
            </div>
          )}
          {d.ideas.length === 0 && <p className="text-sm text-muted">No breakout ideas this session.</p>}
        </div>
      )}
    </Card>
  );
}
