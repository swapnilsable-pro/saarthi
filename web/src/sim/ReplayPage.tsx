import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { inr, simApi, type Mode, type SimIdea, type SimState } from "../api";
import { VERDICT_CLS, VERDICT_ICON } from "../ideas/IdeaDetail";
import { money } from "../perf/charts";
import { Card, Pill, Skeleton, Term } from "../ui";
import { SimChart } from "./SimChart";

const SPEEDS = [{ label: "1×", ms: 2000 }, { label: "4×", ms: 500 }, { label: "15×", ms: 130 }];

export function ReplayPage({ mode, rid, go }: { mode: Mode; rid: string | null; go: (path: string) => void }) {
  return rid ? <SimSession id={rid} onExit={() => go("replay")} /> : <SimSetup mode={mode} onStart={(id) => go(`replay/${id}`)} />;
}

function SimSetup({ mode, onStart }: { mode: Mode; onStart: (id: string) => void }) {
  const days = useQuery({ queryKey: ["sim-days", mode], queryFn: () => simApi.days(mode) });
  const [day, setDay] = useState<string>("");
  const create = useMutation({ mutationFn: (surprise: boolean) => simApi.create(mode, surprise ? { surprise } : { day }), onSuccess: (s) => onStart(s.id) });
  useEffect(() => { if (days.data?.days.length && !day) setDay(days.data.days[days.data.days.length - 1]); }, [days.data, day]);
  return (
    <section className="mx-auto max-w-2xl rounded-xl border border-line bg-panel p-6">
      <h1 className="text-lg font-semibold">Replay a session, bar by bar</h1>
      <p className="mt-2 text-sm text-muted">
        A flight simulator for the trading day. The clock starts at 09:15 and you only ever see bars that have finished,
        and ideas once Saarthi would have made them. Trade on paper as the day unfolds, then compare yourself with Saarthi's plan and with perfect hindsight.
        Replay trades never touch your Paper Desk account.
      </p>
      {days.isLoading ? <Skeleton h={60} /> : !days.data?.days.length ? (
        <p className="mt-4 text-sm text-stop">No replayable sessions yet{mode === "live" ? ": live replays need saved 60-session charts (fetched once Yahoo allows)." : "."}</p>
      ) : (
        <div className="mt-5 flex flex-wrap items-end gap-3">
          <label className="text-xs text-muted">Session
            <select value={day} onChange={(e) => setDay(e.target.value)} className="mt-1 block h-9 rounded-md border border-line bg-panel px-2 text-sm text-text">
              {[...days.data.days].reverse().map((d) => <option key={d} value={d}>{d} · {new Date(d + "T00:00:00Z").toLocaleDateString("en-IN", { weekday: "short", timeZone: "UTC" })}</option>)}
            </select>
          </label>
          <button onClick={() => create.mutate(false)} disabled={create.isPending} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60">
            {create.isPending ? "Preparing…" : "Start replay"}
          </button>
          <span className="text-xs text-faint">or</span>
          <button onClick={() => create.mutate(true)} disabled={create.isPending} className="h-9 rounded-lg border border-line px-4 text-sm font-medium hover:border-accent">
            Surprise me <span className="text-xs text-faint">(date and name hidden)</span>
          </button>
        </div>
      )}
      <p className="mt-3 text-[11px] text-faint">Instruments: {days.data?.symbols.join(", ")}{mode === "demo" && " (nse-trader-skill's synthetic test series)"}.</p>
      {create.error && <p className="mt-3 text-sm text-stop">{(create.error as Error).message.replace(/^\d+ /, "")}</p>}
    </section>
  );
}

function SimSession({ id, onExit }: { id: string; onExit: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sim", id], queryFn: () => simApi.get(id) });
  const set = (s: SimState) => qc.setQueryData(["sim", id], s);
  const adv = useMutation({ mutationFn: (b: { bars?: number; to?: string; next_event?: boolean }) => simApi.advance(id, b), onSuccess: set });
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [focus, setFocus] = useState(0);
  const [picked, setPicked] = useState<SimIdea | null>(null);
  const s = q.data;
  const busy = useRef(false);

  // Playback: one bar per tick, never overlapping requests; stops at the close.
  useEffect(() => {
    if (!playing || !s || s.done) { if (s?.done) setPlaying(false); return; }
    const h = setTimeout(async () => {
      if (busy.current) return;
      busy.current = true;
      try { set(await simApi.advance(id, { bars: 1 })); } finally { busy.current = false; }
    }, SPEEDS[speed].ms);
    return () => clearTimeout(h);
  }, [playing, s, speed, id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const sym = s?.symbols[focus];
  const levels = useMemo(() => {
    const out: { price: number; title: string; tone: "entry" | "stop" | "target" }[] = [];
    const open = s?.trades.find((t) => t.symbol === sym?.symbol && (t.status === "open" || t.status === "working"));
    if (open) {
      if (open.order.entry_price && open.status === "working") out.push({ price: open.order.entry_price, title: open.order.entry_type, tone: "entry" });
      out.push({ price: open.stop_now ?? open.order.stop, title: "Stop", tone: "stop" });
      if (open.order.target) out.push({ price: open.order.target, title: "Target", tone: "target" });
    } else if (picked?.plan && picked.symbol === sym?.symbol) {
      out.push({ price: picked.plan.entry, title: "Plan entry", tone: "entry" }, { price: picked.plan.stop, title: "Plan stop", tone: "stop" }, { price: picked.plan.target, title: "Plan target", tone: "target" });
    }
    return out;
  }, [s, sym, picked]);

  if (!s) return <Skeleton h={400} />;
  const last = sym?.bars[sym.bars.length - 1];
  const pct = Math.max(0, Math.min(1, (toMin(s.time) - 555) / 375));

  return (
    <div className="space-y-4">
      {/* --------------------------------------------------------------- transport */}
      <section className="sticky top-[58px] z-20 rounded-xl border border-line bg-panel/95 px-4 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <button onClick={onExit} className="text-sm text-accent hover:underline">← New replay</button>
          <div>
            <p className="text-xs text-faint">{s.label}{s.surprise && !s.done && " · revealed at the close"}</p>
            <p className="text-2xl font-semibold num">{s.time} <span className="text-sm font-normal text-muted">IST</span></p>
          </div>
          <div className="flex items-center gap-1.5" role="group" aria-label="Replay controls">
            <button onClick={() => setPlaying((p) => !p)} disabled={s.done} className="h-9 w-20 rounded-lg bg-accent text-sm font-semibold text-white disabled:opacity-40" aria-pressed={playing}>
              {playing ? "❚❚ Pause" : "▶ Play"}
            </button>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed" className="h-9 rounded-md border border-line bg-panel px-1.5 text-sm">
              {SPEEDS.map((x, i) => <option key={x.label} value={i}>{x.label}</option>)}
            </select>
            <Btn onClick={() => adv.mutate({ bars: 1 })} disabled={s.done || playing}>+5 min</Btn>
            <Btn onClick={() => adv.mutate({ bars: 6 })} disabled={s.done || playing}>+30 min</Btn>
            <Btn onClick={() => adv.mutate({ next_event: true })} disabled={s.done || playing || !s.next_event}>Next event{s.next_event ? ` (${s.next_event})` : ""}</Btn>
            <Btn onClick={() => adv.mutate({ to: "15:30" })} disabled={s.done || playing}>To close</Btn>
          </div>
          <div className="ml-auto text-right text-sm num">
            <p className="text-xs text-faint">Your P&L</p>
            <p><b className={s.pnl.realized >= 0 ? "text-go" : "text-stop"}>{money(s.pnl.realized)}</b>
              {s.pnl.unrealized !== 0 && <span className="ml-2 text-xs text-muted">open {money(s.pnl.unrealized)}</span>}</p>
          </div>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-panel-2" role="progressbar" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Session progress">
          <div className="h-full bg-accent transition-[width]" style={{ width: `${pct * 100}%` }} />
        </div>
      </section>

      {s.done && s.scorecard && <Scorecard s={s} />}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card title={<>{sym?.symbol} {last && <span className="ml-2 font-normal normal-case text-text num">{last.c.toFixed(2)}</span>}</>}
          right={s.symbols.length > 1 && <div className="flex gap-1">{s.symbols.map((x, i) => <button key={x.symbol} onClick={() => setFocus(i)} className={`rounded px-2 py-0.5 text-xs ${i === focus ? "bg-accent-soft text-accent" : "text-muted"}`}>{x.symbol}</button>)}</div>}>
          {sym && sym.bars.length ? <SimChart bars={sym.bars} levels={levels} trades={s.trades.filter((t) => t.symbol === sym.symbol)} />
            : <div className="flex h-[360px] items-center justify-center text-sm text-muted">The first bar completes at 09:20. Press Play or +5 min.</div>}
          <p className="mt-2 text-[11px] text-faint">Only completed 5-minute bars are shown. The <Term k="orb">opening range</Term> is set at 09:30.</p>
        </Card>
        <div className="space-y-4">
          <SimTicket s={s} sym={sym?.symbol ?? ""} last={last?.c ?? null} picked={picked} onPlaced={set} />
          <Card title={<>Saarthi's ideas <span className="font-normal normal-case text-faint">· {s.ideas.length}</span></>}>
            {s.ideas.length === 0 ? <p className="text-sm text-muted">None yet. Ideas appear when a breakout bar closes{s.next_event ? `; next event at ${s.next_event}` : ""}.</p> :
              <ul className="space-y-2">{s.ideas.map((i) => {
                const vc = VERDICT_CLS[i.verdict];
                return (
                  <li key={i.symbol + i.decided_at} className="rounded-lg border border-line p-2.5 text-sm">
                    <div className="flex items-center justify-between"><b>{i.symbol} <span className="text-xs font-normal text-faint num">{i.decided_at}</span></b>
                      <span className={`rounded px-1.5 py-0.5 text-xs font-bold ${vc.soft} ${vc.text}`}>{VERDICT_ICON[i.verdict]} {i.verdict}</span></div>
                    {i.plan && <p className="mt-1 text-xs num">Buy {i.plan.entry.toFixed(2)} · stop {i.plan.stop.toFixed(2)} · target {i.plan.target.toFixed(2)} · {i.plan.qty} sh</p>}
                    <p className="mt-1 line-clamp-2 text-xs text-muted">{i.reason}</p>
                    {i.plan && !s.done && <button onClick={() => setPicked(i)} className="mt-1.5 text-xs text-accent hover:underline">Use this plan in the ticket</button>}
                  </li>
                );
              })}</ul>}
          </Card>
          <SimTrades s={s} onChange={set} />
        </div>
      </div>
    </div>
  );
}

function Btn(p: { onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return <button onClick={p.onClick} disabled={p.disabled} className="h-9 rounded-md border border-line px-2.5 text-xs font-medium hover:border-accent disabled:opacity-40">{p.children}</button>;
}

const toMin = (hm: string) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };

function SimTicket({ s, sym, last, picked, onPlaced }: { s: SimState; sym: string; last: number | null; picked: SimIdea | null; onPlaced: (x: SimState) => void }) {
  const [t, setT] = useState({ qty: 100, entry_type: "MARKET", entry_price: "" as string | number, stop: "" as string | number, target: "" as string | number });
  useEffect(() => {
    if (picked?.plan) setT({ qty: picked.plan.qty, entry_type: "LIMIT", entry_price: picked.plan.entry, stop: picked.plan.stop, target: picked.plan.target });
  }, [picked]);
  const place = useMutation({
    mutationFn: () => simApi.order(s.id, { symbol: picked?.symbol ?? sym, qty: Number(t.qty), entry_type: t.entry_type,
      entry_price: t.entry_type === "MARKET" ? null : Number(t.entry_price), stop: Number(t.stop), target: t.target === "" ? null : Number(t.target) }),
    onSuccess: onPlaced,
  });
  const risk = last && t.stop !== "" ? (Number(t.entry_type === "MARKET" ? last : t.entry_price) - Number(t.stop)) * Number(t.qty) : null;
  const inp = "mt-1 block h-8 w-full rounded-md border border-line bg-panel px-2 text-sm num";
  return (
    <Card title="Replay ticket" right={<span className="text-[11px] font-semibold text-paper">PAPER · SIM</span>}>
      <div className="grid grid-cols-2 gap-2 text-xs text-muted">
        <label>Qty<input type="number" min={1} value={t.qty} onChange={(e) => setT({ ...t, qty: Number(e.target.value) })} className={inp} /></label>
        <label>Type<select value={t.entry_type} onChange={(e) => setT({ ...t, entry_type: e.target.value })} className={inp}><option value="MARKET">Market (next bar open)</option><option value="LIMIT">Limit</option><option value="SL-M">Buy-stop</option></select></label>
        <label>Price<input type="number" step="0.05" disabled={t.entry_type === "MARKET"} value={t.entry_type === "MARKET" ? "" : t.entry_price} placeholder={last?.toFixed(2)} onChange={(e) => setT({ ...t, entry_price: e.target.value })} className={inp + " disabled:opacity-40"} /></label>
        <label>Stop<input type="number" step="0.05" value={t.stop} onChange={(e) => setT({ ...t, stop: e.target.value })} className={inp} /></label>
        <label className="col-span-2">Target (optional)<input type="number" step="0.05" value={t.target} onChange={(e) => setT({ ...t, target: e.target.value })} className={inp} /></label>
      </div>
      {risk !== null && risk > 0 && <p className="mt-2 text-xs text-muted num">Risk at stop ≈ ₹{inr.format(Math.round(risk))}</p>}
      <button onClick={() => place.mutate()} disabled={s.done || t.stop === "" || place.isPending}
        className="mt-3 w-full rounded-lg bg-paper py-2 text-sm font-semibold text-white disabled:opacity-40">Buy {picked?.symbol ?? sym} (paper, at {s.time})</button>
      {place.error && <p className="mt-2 text-xs text-stop">{(place.error as Error).message.replace(/^\d+ /, "")}</p>}
    </Card>
  );
}

function SimTrades({ s, onChange }: { s: SimState; onChange: (x: SimState) => void }) {
  const close = useMutation({ mutationFn: (tid: string) => simApi.close(s.id, tid), onSuccess: onChange });
  if (!s.trades.length) return null;
  return (
    <Card title="Your replay trades">
      <ul className="space-y-2">{s.trades.map((t) => (
        <li key={t.id} className="rounded-lg border border-line p-2.5 text-sm">
          <div className="flex items-center justify-between gap-2"><b>{t.symbol} <span className="text-xs font-normal text-faint">{t.qty} · {t.order.entry_type}</span></b><Pill tone={t.status === "open" ? "paper" : t.status === "rejected" ? "stop" : "neutral"}>{t.status}</Pill></div>
          {t.reject_reason && <p className="text-xs text-stop">{t.reject_reason}</p>}
          <p className="mt-1 text-xs num">{t.entry_price ? `In ${t.entry_price.toFixed(2)} @ ${t.entry_at?.slice(11)}` : `Waiting since ${t.order.placed_at.slice(11)}`}
            {t.exit_price ? ` · out ${t.exit_price.toFixed(2)} @ ${t.exit_at?.slice(11)} (${t.exit_reason?.toLowerCase().replace("_", " ")})` : t.stop_now ? ` · stop ${t.stop_now.toFixed(2)}` : ""}</p>
          {(t.net_pnl ?? t.unrealized_pnl) !== null && <p className={`text-sm font-semibold num ${(t.net_pnl ?? t.unrealized_pnl ?? 0) >= 0 ? "text-go" : "text-stop"}`}>{money(t.net_pnl ?? t.unrealized_pnl ?? 0)}{t.net_pnl === null && <span className="text-xs font-normal text-muted"> open</span>}</p>}
          {(t.status === "open" || t.status === "working") && !s.done && <button onClick={() => close.mutate(t.id)} className="mt-1 text-xs text-stop hover:underline">{t.status === "open" ? "Sell at next bar's open" : "Cancel"}</button>}
        </li>))}</ul>
    </Card>
  );
}

function Scorecard({ s }: { s: SimState }) {
  const c = s.scorecard!;
  const tiles = [
    { k: "You", v: c.you.net, sub: `${c.you.trades} trade${c.you.trades === 1 ? "" : "s"}` },
    { k: "Saarthi: every TAKE", v: c.saarthi_take.net, sub: `${c.saarthi_take.trades} trade(s), as planned` },
    { k: "Every idea, as planned", v: c.every_idea.net, sub: `${c.every_idea.trades} trade(s), incl. SKIPs` },
    { k: "Perfect hindsight", v: c.hindsight?.net ?? 0, sub: c.hindsight ? `${c.hindsight.symbol}: buy ${c.hindsight.buy.toFixed(2)} @ ${c.hindsight.buy_at}, sell ${c.hindsight.sell.toFixed(2)} @ ${c.hindsight.sell_at}` : "no up-move" },
  ];
  return (
    <section className="rounded-xl border border-accent/40 bg-panel p-4">
      <h2 className="text-base font-semibold">Session over · {s.day}{s.surprise && <span className="ml-2 text-sm font-normal text-muted">revealed: {s.symbols.map((x) => x.real).join(", ")}</span>}</h2>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.k} className="rounded-lg bg-panel-2 p-3">
            <p className="text-xs text-faint">{t.k}</p>
            <p className={`text-xl font-semibold num ${t.v >= 0 ? "text-go" : "text-stop"}`}>{money(t.v)}</p>
            <p className="text-[11px] text-muted">{t.sub}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm text-muted">
        {c.capture_pct !== null && c.you.net > 0 && <>You captured <b className="text-text">{c.capture_pct}%</b> of the best possible move. </>}
        {c.you.trades > 0 && c.you.net <= 0 && c.hindsight && <>You finished at {money(c.you.net)} on a day when {money(c.hindsight.net)} was available with hindsight. </>}
        Hindsight is a ceiling nobody reaches; the useful comparison is you versus the plan.
        {c.ideas.length > 0 && <> Saarthi's ideas today: {c.ideas.map((i) => `${i.symbol} ${i.verdict} at ${i.decided_at} (${i.ghost_net !== null ? money(i.ghost_net) : "not filled"})`).join("; ")}.</>}
      </p>
    </section>
  );
}
