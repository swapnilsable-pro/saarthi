import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ideasApi, inr, type Costs, type Gate, type Idea, type Odds, type Plan } from "../api";
import { Card, EvidenceLink, Pill, Skeleton, Term } from "../ui";
import { ProOnly } from "../prefs";
import { Narrator } from "../learn/Narrator";
import { IdeaChart } from "./IdeaChart";

export const VERDICT_TONE = { TAKE: "go", WATCH: "caution", SKIP: "stop" } as const;
export const VERDICT_ICON = { TAKE: "●", WATCH: "◐", SKIP: "○" } as const;
export const VERDICT_CLS = {
  TAKE: { soft: "bg-go-soft", text: "text-go" },
  WATCH: { soft: "bg-caution-soft", text: "text-caution" },
  SKIP: { soft: "bg-stop-soft", text: "text-stop" },
} as const;
const rs = (v: number) => `₹${inr.format(Math.round(v))}`;
const sgn = (v: number) => `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(Math.round(v)))}`;
const pct = (v: number) => `${Math.round(v * 100)}%`;

export function IdeaDetail({ id, onBack, onTrade }: { id: string; onBack: () => void; onTrade: () => void }) {
  const q = useQuery({ queryKey: ["idea", id], queryFn: () => ideasApi.get(id) });
  const [hindsight, setHindsight] = useState(false);
  const barsQ = useQuery({ queryKey: ["idea-bars", id, hindsight], queryFn: () => ideasApi.bars(id, hindsight) });
  const d = q.data;

  if (q.isLoading) return <Skeleton h={420} />;
  if (!d) return <p className="text-stop">Idea not found.</p>;
  const { plan, odds, costs, detail } = d;
  const vc = VERDICT_CLS[d.verdict];

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-sm text-accent hover:underline">← All ideas</button>

      {/* ---------------------------------------------------------------- header */}
      <section className="rounded-xl border border-line bg-panel p-4">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{d.symbol}</h1>
              <span className="text-sm text-muted">{detail.name}</span>
              <Pill tone="neutral">Opening-range breakout · long</Pill>
              {detail.synthetic && <Pill tone="paper" title="DEMO is nse-trader-skill's generated test instrument, not a real stock">synthetic test data</Pill>}
            </div>
            <p className="mt-1 text-sm text-muted num">
              {d.mode === "demo" ? "Demo session" : "Live session"} {d.session_day} · decided at {d.decided_at} IST · mood {detail.mood.level.replace("_", " ")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className={`rounded-lg px-3 py-2 text-center ${vc.soft}`}>
              <p className={`text-lg leading-none font-bold ${vc.text}`}>{VERDICT_ICON[d.verdict]} {d.verdict}</p>
              <p className="mt-1 text-[11px] text-muted num">score {d.score.toFixed(0)}/100</p>
            </div>
            <button onClick={onTrade} disabled={!plan} title={plan ? "Open a paper ticket prefilled with this plan" : "No plan to trade"}
              className="rounded-lg bg-paper px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">
              Paper trade ▶<span className="block text-[10px] font-normal opacity-80">simulated, not real</span>
            </button>
          </div>
        </div>
        <p className={`mt-3 rounded-lg p-3 text-sm ${vc.soft}`}>
          <b className={vc.text}>{d.verdict === "TAKE" ? "Why take it: " : d.verdict === "WATCH" ? "Why watch: " : "Why skip: "}</b>
          {detail.reason}
        </p>
      </section>

      {/* ---------------------------------------------------------------- chart + plan */}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card title="Price, 5-minute bars" right={
          <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={hindsight} onChange={(e) => setHindsight(e.target.checked)} className="accent-[var(--accent)]" />
            Show what happened next (hindsight)
          </label>}>
          {barsQ.data?.bars.length ? (
            <IdeaChart bars={barsQ.data.bars} plan={plan} day={d.session_day} breakoutAt={detail.breakout.at}
              decidedAt={d.as_of} hindsight={hindsight} />
          ) : <Skeleton h={340} />}
          <p className="mt-2 text-[11px] text-faint">
            {hindsight ? "Hindsight view: bars after the decision are shown. The decision did not see them."
              : `Bars up to the decision at ${d.as_of.slice(11)} IST only, exactly what the tools saw.`}
          </p>
        </Card>
        {plan ? <PlanCard plan={plan} /> : <Card title="The plan"><p className="text-sm text-muted">No plan: the Time Machine could not run.</p></Card>}
      </div>

      {/* ---------------------------------------------------------------- odds, timing, costs */}
      {plan && odds && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <OddsCard odds={odds} plan={plan} />
          <TimingCard idea={d} />
          {costs && <CostCard costs={costs} plan={plan} odds={odds} />}
        </div>
      )}

      {/* ---------------------------------------------------------------- evidence */}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card title="Evidence checklist">
          <ul className="divide-y divide-line">
            {detail.gates.map((g) => <GateRow key={g.step} g={g} />)}
          </ul>
          <details className="mt-3 text-xs text-muted">
            <summary className="cursor-pointer text-accent">The exact verdict rule</summary>
            <p className="mt-1.5 rounded-lg bg-panel-2 p-2.5 leading-relaxed">{detail.verdict_rule}</p>
          </details>
        </Card>
        <div className="space-y-4">
          <Card title="In plain English"><p className="text-sm leading-relaxed">{detail.narrative}</p>
            <p className="mt-2 text-[11px] text-faint">Template text filled only with the tool outputs above.</p></Card>
          <Narrator id={d.id} />
          <ProOnly>{detail.variants.length > 0 && <VariantsCard idea={d} />}</ProOnly>
          <ProOnly>{detail.score_terms.length > 0 && (
            <Card title={<>Score {d.score.toFixed(0)}/100 <span className="font-normal normal-case text-faint">· ranking only, never the verdict</span></>}>
              <ul className="space-y-1.5 text-sm">
                {detail.score_terms.map((t) => (
                  <li key={t.term} className="flex items-center gap-3">
                    <span className="w-36 shrink-0">{t.term}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel-2">
                      {t.value !== null && <div className="h-full bg-accent" style={{ width: `${t.value * 100}%` }} />}
                    </div>
                    <span className="w-44 shrink-0 text-right text-xs text-muted">{t.value === null ? "not counted · " : ""}{t.why} · w{t.weight}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}</ProOnly>
        </div>
      </div>
    </div>
  );
}

function GateRow({ g }: { g: Gate }) {
  const icon = g.status === "pass" ? <span className="text-go">✓</span> : g.status === "fail" ? <span className="text-stop">✕</span>
    : g.status === "na" ? <span className="text-faint">–</span> : <span className="text-caution">?</span>;
  return (
    <li className="flex items-start gap-3 py-2">
      <span className="mt-0.5 w-4 text-center font-bold" aria-label={g.status}>{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm"><span className="font-mono text-[11px] text-faint">{g.step}</span> <span className="font-medium">{g.label}</span>
          {!g.required && <span className="ml-1 text-[11px] text-faint">(advisory)</span>}
          {g.status === "no_data" && <span className="ml-1 text-[11px] text-caution">no data</span>}
          {g.status === "na" && <span className="ml-1 text-[11px] text-faint">n/a</span>}</p>
        <p className="mt-0.5 text-xs text-muted">{g.summary}</p>
      </div>
      <EvidenceLink runId={g.run_id} label={`${g.step} ${g.label}`} />
    </li>
  );
}

function PlanCard({ plan }: { plan: Plan }) {
  const w = plan.best_window;
  return (
    <Card title="The plan" right={<EvidenceLink runId={plan.size_run_id} label="Position size (position-sizing/risk.py size)">size</EvidenceLink>}>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-sm num">
        <dt className="text-muted">Buy at <span className="text-faint">(close of breakout bar)</span></dt><dd className="font-semibold text-accent">{plan.entry.toFixed(2)}</dd>
        <dt className="text-muted"><Term k="orb">Trigger</Term> (OR high + 1 tick)</dt><dd>{plan.trigger.toFixed(2)}</dd>
        <dt className="text-muted">Stop · {plan.stop_label.toLowerCase()}</dt><dd className="font-semibold text-stop">{plan.stop.toFixed(2)}</dd>
        <dt className="text-muted">+1R → stop to breakeven</dt><dd>{plan.t1.toFixed(2)}</dd>
        <dt className="text-muted">Target ({plan.target_r}R)</dt><dd className="font-semibold text-go">{plan.target.toFixed(2)}</dd>
        <dt className="text-muted">Quantity</dt><dd>{inr.format(plan.qty)} shares</dd>
        <dt className="text-muted">Position value</dt><dd>{rs(plan.position_value)}</dd>
        <dt className="text-muted">Risk at stop</dt><dd>{rs(plan.risk_amount)} <span className="text-faint">({plan.risk_per_share.toFixed(2)}/sh)</span></dd>
      </dl>
      {plan.sizing_notes.length > 0 && <p className="mt-2 text-[11px] text-faint">{plan.sizing_notes.join(" ")}</p>}

      <div className="mt-4 rounded-lg bg-panel-2 p-3">
        <p className="text-xs font-medium tracking-wide text-faint uppercase">When</p>
        {w?.from ? (
          <p className="mt-1 text-sm">Best entry <b className="num">{w.from}–{w.to}</b>{w.edge_ends && <span className="text-muted"> · edge gone after {w.edge_ends}</span>}</p>
        ) : <p className="mt-1 text-sm text-stop">{w?.note ?? "No positive entry window."}</p>}
        <p className="mt-0.5 text-xs text-muted num">No new entries after {plan.no_entries_after} · <Term k="square_off">square-off</Term> {plan.flat_by}</p>
      </div>

      <p className="mt-4 mb-1 text-xs font-medium tracking-wide text-faint uppercase">Exit ladder</p>
      <ol className="space-y-1 text-sm">
        {plan.exit_ladder.map((s, i) => (
          <li key={i} className="flex items-start justify-between gap-2">
            <span><span className="text-faint num">{i + 1}.</span> <span className="num">{s.at}</span>: <span className="text-muted">{s.action}{s.stop ? ` (stop ${s.stop.toFixed(2)})` : ""}</span></span>
            {s.run_id && <EvidenceLink runId={s.run_id} label="Trailing-stop ladder (position-sizing/risk.py trail)">trail</EvidenceLink>}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function OddsCard({ odds, plan }: { odds: Odds; plan: Plan }) {
  const seg = [
    { k: "Target first", v: odds.p_target, cls: "bg-go" },
    { k: "Stop first", v: odds.p_stop, cls: "bg-stop" },
    { k: `Neither by ${plan.flat_by}`, v: odds.p_neither, cls: "bg-faint" },
  ];
  const h = odds.history;
  return (
    <Card title="The odds · Time Machine" right={<EvidenceLink runId={odds.run_id} label="Time Machine (nse-timemachine/timemachine.py run)" />}>
      <p className="text-xs text-muted num">{inr.format(odds.trials)} simulated rests-of-session, drawn from {odds.sessions} past sessions of this stock's own 5-minute bars</p>
      <div className="mt-2 flex h-3 overflow-hidden rounded-full" role="img" aria-label={seg.map((s) => `${s.k} ${pct(s.v)}`).join(", ")}>
        {seg.map((s) => <div key={s.k} className={s.cls} style={{ flex: s.v }} />)}
      </div>
      <ul className="mt-2 grid grid-cols-3 gap-2 text-xs">
        {seg.map((s) => <li key={s.k}><span className={`mr-1 inline-block h-2 w-2 rounded-sm ${s.cls}`} />{s.k}<br /><b className="text-base num">{pct(s.v)}</b></li>)}
      </ul>
      <dl className="mt-4 grid grid-cols-2 gap-y-2 text-sm num">
        <dt className="text-muted">Net expectancy</dt><dd className={`text-right font-semibold ${odds.net_per_trade >= 0 ? "text-go" : "text-stop"}`}>{sgn(odds.net_per_trade)} / trade</dd>
        <dt className="text-muted">Before costs</dt><dd className="text-right">{sgn(odds.gross_per_trade)}</dd>
        <dt className="text-muted">Reward:risk net (gross)</dt><dd className="text-right">{odds.net_rr.toFixed(2)} ({odds.gross_rr.toFixed(2)})</dd>
        <dt className="text-muted">Breakeven per share</dt><dd className="text-right">₹{odds.breakeven_per_share.toFixed(2)}</dd>
      </dl>
      <div className="mt-4 rounded-lg bg-panel-2 p-3 text-sm">
        <p className="text-xs font-medium tracking-wide text-faint uppercase">History: same rule, past sessions</p>
        <p className="mt-1">Fired on <b>{h.sessions_fired}</b> sessions · target first <b>{pct(h.p_target)}</b> · stop first {pct(h.p_stop)}</p>
        <p className="text-xs text-muted num">Average {sgn(h.net_per_trade)} a trade after costs</p>
      </div>
      {odds.ambiguous_bars > 0 && <p className="mt-2 text-[11px] text-faint">{odds.ambiguous_bars} bar(s) touched both stop and target; counted as stop (pessimistic).</p>}
    </Card>
  );
}

function TimingCard({ idea }: { idea: Idea }) {
  const c = idea.detail.timing;
  const w = idea.plan?.best_window;
  if (!c.length) return <Card title="When to enter"><p className="text-sm text-muted">No timing curve.</p></Card>;
  const max = Math.max(...c.map((x) => Math.abs(x.net_per_trade)), 1);
  const inWin = (at: string) => !!w?.from && at >= w.from && at <= (w.to ?? "");
  return (
    <Card title="When to enter · net expectancy by entry time">
      <div className="relative flex h-40 items-center gap-[3px]" role="img"
        aria-label={`Net expectancy by entry time from ${c[0].at} to ${c[c.length - 1].at}`}>
        <div className="absolute inset-x-0 top-1/2 border-t border-line" />
        {c.map((x) => {
          const hgt = (Math.abs(x.net_per_trade) / max) * 50;
          const pos = x.net_per_trade >= 0;
          return (
            <div key={x.at} className="relative h-full flex-1" title={`${x.at}: ${sgn(x.net_per_trade)} per trade, target first ${pct(x.p_target)}`}>
              <div className={`absolute inset-x-0 rounded-sm ${pos ? (inWin(x.at) ? "bg-go" : "bg-go/50") : "bg-stop/60"}`}
                style={pos ? { bottom: "50%", height: `${hgt}%` } : { top: "50%", height: `${hgt}%` }} />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-faint num"><span>{c[0].at}</span><span>{c[Math.floor(c.length / 2)].at}</span><span>{c[c.length - 1].at}</span></div>
      <p className="mt-3 text-sm">
        {w?.from ? <>Enter between <b className="num">{w.from}</b> and <b className="num">{w.to}</b>; the edge peaks at {w.peak_at} ({sgn(w.peak)}).</>
          : <span className="text-stop">No entry time is profitable after costs for this plan.</span>}
      </p>
      <p className="mt-1 text-[11px] text-faint">Same entry, stop and target, simulated as if entered at each later time ({inr.format(Number(idea.config_snapshot.scan_trials ?? 2000))} runs each).</p>
    </Card>
  );
}

function CostCard({ costs, plan, odds }: { costs: Costs; plan: Plan; odds: Odds }) {
  const gross = (plan.target - plan.entry) * plan.qty;
  const legs = Object.entries(costs.at_target.legs).filter(([, v]) => v > 0.005).sort((a, b) => b[1] - a[1]);
  const names: Record<string, string> = { brokerage: "Brokerage", stt: "STT", stamp: "Stamp duty", txn: "Exchange", sebi: "SEBI fee", ipft: "IPFT", gst: "GST" };
  const net = gross - costs.at_target.total;
  return (
    <Card title="Cost of this trade, if the target hits" right={<EvidenceLink runId={costs.india_run_id} label="Charges cross-check (trading-costs/charges.py)">cross-check</EvidenceLink>}>
      <ul className="space-y-1 text-sm num">
        <li className="flex justify-between"><span>Gross profit at target</span><b className="text-go">{sgn(gross)}</b></li>
        {legs.map(([k, v]) => (
          <li key={k} className="flex items-center justify-between gap-3">
            <span className="text-muted">− {names[k] ?? k}</span>
            <span className="flex flex-1 items-center justify-end gap-2">
              <span className="h-1.5 rounded-full bg-stop/60" style={{ width: `${Math.max(2, (v / costs.at_target.total) * 120)}px` }} />
              <span className="w-16 text-right">₹{v.toFixed(2)}</span>
            </span>
          </li>
        ))}
        <li className="flex justify-between border-t border-line pt-1.5"><span>Net at target</span><b className={net >= 0 ? "text-go" : "text-stop"}>{sgn(net)}</b></li>
        <li className="flex justify-between text-muted"><span>Charges if stopped out</span><span>₹{costs.at_stop.total.toFixed(2)}</span></li>
      </ul>
      <p className="mt-3 text-xs text-muted">
        Costs are {Math.round((costs.at_target.total / Math.max(1, gross)) * 100)}% of the gross win and
        ₹{odds.breakeven_per_share.toFixed(2)} a share to break even.{" "}
        {costs.cross_check_delta !== null && (Math.abs(costs.cross_check_delta) <= 1
          ? <span className="text-go">✓ Both repos' calculators agree (Δ ₹{Math.abs(costs.cross_check_delta).toFixed(2)}).</span>
          : <span className="text-caution">⚠ Calculators differ by ₹{costs.cross_check_delta.toFixed(2)}.</span>)}
      </p>
    </Card>
  );
}

function VariantsCard({ idea }: { idea: Idea }) {
  const chosen = idea.plan;
  return (
    <Card title="Plans tested">
      <table className="w-full text-sm num">
        <thead className="text-xs text-muted"><tr>
          <th className="py-1 text-left font-medium">Stop</th><th className="text-right font-medium">Target</th>
          <th className="text-right font-medium">P(target)</th><th className="text-right font-medium">Net R:R</th>
          <th className="text-right font-medium">Net / trade</th><th />
        </tr></thead>
        <tbody>
          {idea.detail.variants.map((v) => {
            const sel = chosen && v.stop_method === chosen.stop_method && v.target_r === chosen.target_r;
            return (
              <tr key={v.stop_method + v.target_r} className={`border-t border-line ${sel ? "bg-accent-soft" : ""}`}>
                <td className="py-1.5">{v.stop_method === "or_mid" ? "OR mid" : "OR low"} {v.stop.toFixed(2)}</td>
                <td className="text-right">{v.target_r}R</td>
                <td className="text-right">{v.odds ? pct(v.odds.p_target) : "–"}</td>
                <td className="text-right">{v.odds?.net_rr.toFixed(2) ?? "–"}</td>
                <td className={`text-right ${v.odds && v.odds.net_per_trade >= 0 ? "text-go" : "text-stop"}`}>{v.odds ? sgn(v.odds.net_per_trade) : "–"}</td>
                <td className="pl-2 text-right"><EvidenceLink runId={v.run_id} label={`Time Machine: ${v.stop_method} ${v.target_r}R`}>run</EvidenceLink></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-faint">Highlighted: the plan chosen (best net expectancy among those meeting the minimum net reward:risk). Choosing among 6 plans on the same history slightly flatters the winner, so judge it by the full 10,000-run odds and the calibration page (Phase 4).</p>
    </Card>
  );
}
