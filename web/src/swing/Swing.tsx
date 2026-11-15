import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { inr, paperApi, swingApi, type Mode, type SwingIdea } from "../api";
import { VERDICT_CLS, VERDICT_ICON } from "../ideas/IdeaDetail";
import { money } from "../perf/charts";
import { Card, EvidenceLink, Pill, Skeleton } from "../ui";
import { DailyChart } from "./DailyChart";
import { Narrator } from "../learn/Narrator";

export function SwingList({ mode, open }: { mode: Mode; open: (id: string) => void }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["swing", mode], queryFn: () => swingApi.list(mode) });
  const scan = useMutation({ mutationFn: () => swingApi.scan(mode), onSuccess: () => qc.invalidateQueries({ queryKey: ["swing", mode] }) });
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel p-4">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="min-w-[260px] flex-1">
            <h1 className="text-base font-semibold">Swing ideas · multi-day breakouts (delivery)</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">
              After the close, claude-trading-skills-india's breakout planner scans daily charts for Stage-2 stocks building a tight base,
              plans a GTT buy above the pivot with a chase limit, a stop and 2R/3R targets, and its backtester tests the same breakout on the
              stock's own history after costs. {mode === "demo" ? "Demo: the evening of Fri 18 Sep 2026 on the India repo's daily fixtures." : ""}
            </p>
          </div>
          <button onClick={() => scan.mutate()} disabled={scan.isPending} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60">
            {scan.isPending ? "Scanning…" : "Scan for swing setups"}
          </button>
        </div>
        {scan.data && <p className="mt-3 rounded-lg bg-panel-2 p-3 text-sm">{scan.data.error ?? <>Scanned <b>{scan.data.scanned}</b> stocks as of {scan.data.as_of}: <b>{scan.data.decisions.length}</b> new idea(s){scan.data.decisions.length ? ` (${scan.data.decisions.map((d) => `${d.symbol} ${d.verdict}`).join(", ")})` : " (already scanned)"}.</>}</p>}
      </section>
      {list.isLoading ? <Skeleton h={160} /> : !list.data?.ideas.length ? (
        <Card><p className="py-6 text-center text-sm text-muted">No swing ideas yet. Run the scan.</p></Card>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
          {list.data.ideas.map((i) => {
            const vc = VERDICT_CLS[i.verdict];
            const bt = i.odds as Record<string, number | null> | null;
            return (
              <button key={i.id} onClick={() => open(i.id)} className="rounded-xl border border-line bg-panel p-4 text-left hover:border-accent">
                <div className="flex items-start justify-between gap-3">
                  <div><span className="text-base font-semibold">{i.symbol}</span> <span className="text-xs text-muted num">evening of {i.session_day}</span>
                    {i.synthetic && <span className="ml-2"><Pill tone="paper">fixture</Pill></span>}</div>
                  <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-bold ${vc.soft} ${vc.text}`}>{VERDICT_ICON[i.verdict]} {i.verdict}</span>
                </div>
                {i.plan?.trigger && (
                  <dl className="mt-3 grid grid-cols-4 gap-2 text-sm num">
                    <div><dt className="text-[11px] text-faint">GTT trigger</dt><dd className="font-medium">{i.plan.trigger.toFixed(2)}</dd></div>
                    <div><dt className="text-[11px] text-faint">Stop</dt><dd className="font-medium text-stop">{i.plan.stop.toFixed(2)}</dd></div>
                    <div><dt className="text-[11px] text-faint">2R target</dt><dd className="font-medium text-go">{i.plan.target?.toFixed(2) ?? "–"}</dd></div>
                    <div><dt className="text-[11px] text-faint">Qty</dt><dd className="font-medium">{inr.format(i.plan.qty)}</dd></div>
                  </dl>
                )}
                {bt && <p className="mt-2 text-xs text-muted num">History: {bt.trades ?? 0} breakout trades · {bt.expectancy_r != null ? `${Number(bt.expectancy_r).toFixed(2)}R/trade` : "–"} · PF {bt.profit_factor ?? "–"}</p>}
                <p className={`mt-2 line-clamp-2 text-xs ${i.verdict === "TAKE" ? "text-muted" : vc.text}`}>{i.reason}</p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function SwingDetail({ id, mode, onBack, onDesk }: { id: string; mode: Mode; onBack: () => void; onDesk: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["swing-idea", id], queryFn: () => swingApi.get(id) });
  const [hindsight, setHindsight] = useState(false);
  const d = q.data;
  const bars = useQuery({ queryKey: ["daily", mode, d?.symbol, hindsight, d?.session_day], enabled: !!d,
    queryFn: () => swingApi.daily(mode, d!.symbol, hindsight ? undefined : d!.session_day) });
  const trades = useQuery({ queryKey: ["swing-trades", id], queryFn: () => paperApi.trades(mode, { idea: id }) });
  const gtt = useMutation({ mutationFn: () => swingApi.gtt(mode, id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["swing-trades", id] }); qc.invalidateQueries({ queryKey: ["paper-trades", mode] }); } });
  const p = d?.plan;
  const levels = useMemo(() => p ? [
    { price: p.pivot, title: "Pivot", tone: "muted" as const }, { price: p.trigger, title: "GTT trigger", tone: "entry" as const },
    { price: p.stop, title: "Stop", tone: "stop" as const }, ...(p.target ? [{ price: p.target, title: "2R", tone: "target" as const }] : []),
  ] : [], [p]);
  const t0 = trades.data?.trades[0];
  const marks = useMemo(() => [
    ...(d ? [{ date: d.session_day, text: "decided", tone: "muted" as const, above: true }] : []),
    ...(hindsight && t0?.entry_at ? [{ date: t0.entry_at, text: `GTT buy ${t0.entry_price?.toFixed(2)}`, tone: "entry" as const }] : []),
    ...(hindsight && t0?.exit_at ? [{ date: t0.exit_at, text: `${t0.exit_reason?.toLowerCase().replace("_", " ")} ${t0.exit_price?.toFixed(2)}`, tone: "exit" as const, above: true }] : []),
  ], [d, t0, hindsight]);
  if (!d) return <Skeleton h={400} />;
  const vc = VERDICT_CLS[d.verdict];
  const bt = d.odds?.backtest ?? {};

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-sm text-accent hover:underline">← All swing ideas</button>
      <section className="rounded-xl border border-line bg-panel p-4">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold">{d.symbol} <Pill tone="neutral">Swing breakout · CNC</Pill> {d.detail.synthetic && <Pill tone="paper">India repo fixture data</Pill>}</h1>
            <p className="mt-1 text-sm text-muted">Decided the evening of {d.session_day} · market {d.detail.mood.label ?? "unknown"}</p>
          </div>
          <div className={`rounded-lg px-3 py-2 text-center ${vc.soft}`}><p className={`text-lg font-bold leading-none ${vc.text}`}>{VERDICT_ICON[d.verdict]} {d.verdict}</p><p className="mt-1 text-[11px] text-muted">score {d.score.toFixed(0)}</p></div>
          <button onClick={() => gtt.mutate()} disabled={!p?.trigger || gtt.isPending} className="rounded-lg bg-paper px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">
            Paper GTT ▶<span className="block text-[10px] font-normal opacity-80">simulated, not real</span>
          </button>
        </div>
        <p className={`mt-3 rounded-lg p-3 text-sm ${vc.soft}`}><b className={vc.text}>{d.verdict === "TAKE" ? "Why take it: " : d.verdict === "WATCH" ? "Why watch: " : "Why skip: "}</b>{d.detail.reason}</p>
        {gtt.data && <p className="mt-2 text-sm">Paper GTT placed: <b>{gtt.data.status}</b>{gtt.data.entry_at && <> · bought {gtt.data.entry_price?.toFixed(2)} on {gtt.data.entry_at}</>}{gtt.data.exit_reason && <> · {gtt.data.exit_reason.toLowerCase().replace("_", " ")} {money(gtt.data.net_pnl ?? 0)}</>}{gtt.data.reject_reason && <span className="text-stop"> · {gtt.data.reject_reason}</span>} <button onClick={onDesk} className="ml-1 text-accent underline">open Paper Desk</button></p>}
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card title="Daily chart" right={<label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={hindsight} onChange={(e) => setHindsight(e.target.checked)} className="accent-[var(--accent)]" />Show what happened next</label>}>
          {bars.data?.bars.length ? <DailyChart bars={bars.data.bars} levels={levels} marks={marks} /> : <Skeleton h={320} />}
          <p className="mt-2 text-[11px] text-faint">{hindsight ? "Hindsight: sessions after the decision, with your paper GTT's fills if you placed one." : `Sessions up to the evening of ${d.session_day}, exactly what the tools saw.`}</p>
        </Card>
        {p?.trigger ? (
          <Card title="The plan · breakout planner" right={<EvidenceLink runId={p.plan_run_id} label="Breakout plan (breakout-planner/breakout.py plan)" />}>
            <dl className="grid grid-cols-[1fr_auto] gap-y-1.5 text-sm num">
              <dt className="text-muted">Pivot</dt><dd>{p.pivot.toFixed(2)}</dd>
              <dt className="text-muted">GTT trigger / chase limit</dt><dd className="font-semibold text-accent">{p.trigger.toFixed(2)} / {p.limit.toFixed(2)}</dd>
              <dt className="text-muted">Stop ({p.stop_method})</dt><dd className="font-semibold text-stop">{p.stop.toFixed(2)}</dd>
              {p.targets.map((t) => <Fragment key={t.R}><dt className="text-muted">Target {t.R}R</dt><dd className="text-go">{t.price.toFixed(2)} <span className="text-xs text-faint">{money(t.net_pnl)} net</span></dd></Fragment>)}
              <dt className="text-muted">Quantity</dt><dd>{inr.format(p.qty)} · ₹{inr.format(Math.round(p.position_value))}</dd>
              <dt className="text-muted">Risk if stopped</dt><dd>₹{inr.format(Math.round(p.risk_if_stopped))}</dd>
              <dt className="text-muted">Hold up to</dt><dd>{p.hold_days} sessions</dd>
            </dl>
            <p className="mt-3 mb-1 text-xs font-medium tracking-wide text-faint uppercase">Orders, in the planner's words</p>
            <ul className="space-y-1.5 text-xs text-muted">{Object.entries(p.orders).map(([k, v]) => <li key={k}><b className="text-text">{k.replace("_", " ")}:</b> {v}</li>)}</ul>
            {p.warnings.length > 0 && <div className="mt-3 rounded-md bg-caution-soft p-2 text-xs text-caution">{p.warnings.map((w) => <p key={w}>⚠ {w}</p>)}</div>}
          </Card>
        ) : <Card title="The plan"><p className="text-sm text-muted">No tradable plan.</p></Card>}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-2">
        <Card title="Evidence checklist">
          <ul className="divide-y divide-line">{d.detail.gates.map((g) => (
            <li key={g.step} className="flex items-start gap-3 py-2">
              <span className="mt-0.5 w-4 text-center font-bold">{g.status === "pass" ? <span className="text-go">✓</span> : g.status === "fail" ? <span className="text-stop">✕</span> : <span className="text-caution">?</span>}</span>
              <div className="min-w-0 flex-1"><p className="text-sm"><span className="font-mono text-[11px] text-faint">{g.step}</span> <span className="font-medium">{g.label}</span>{!g.required && <span className="ml-1 text-[11px] text-faint">(advisory)</span>}</p><p className="mt-0.5 text-xs text-muted">{g.summary}</p></div>
              <EvidenceLink runId={g.run_id} label={`${g.step} ${g.label}`} />
            </li>))}</ul>
          <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer text-accent">The exact verdict rule</summary><p className="mt-1.5 rounded-lg bg-panel-2 p-2.5">{d.detail.verdict_rule}</p></details>
        </Card>
        <div className="space-y-4">
          <Card title={`History · ${d.odds?.strategy ?? "backtest"} on this stock`} right={<EvidenceLink runId={d.odds?.run_id} label="Backtest (backtest-lab/backtest.py run)" />}>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm num">
              {[["Trades", bt.trades], ["Win rate", bt.win_rate_pct != null ? `${Number(bt.win_rate_pct).toFixed(0)}%` : "–"],
                ["Expectancy", bt.expectancy_r != null ? `${Number(bt.expectancy_r).toFixed(2)}R` : "–"], ["Profit factor", bt.profit_factor ?? "–"],
                ["Max drawdown", bt.max_drawdown_pct != null ? `${Number(bt.max_drawdown_pct).toFixed(1)}%` : "–"], ["Avg hold", bt.avg_bars_held != null ? `${Number(bt.avg_bars_held).toFixed(0)} sessions` : "–"],
                ["Period", `${bt.start_date ?? "?"} → ${bt.end_date ?? "?"}`], ["Costs", bt.charges_pct_of_gross_profit != null ? `${Number(bt.charges_pct_of_gross_profit).toFixed(1)}% of gross` : "–"]]
                .map(([k, v]) => <div key={String(k)}><dt className="text-[11px] text-faint">{k}</dt><dd>{String(v ?? "–")}</dd></div>)}
            </dl>
            {(d.odds?.red_flags.length ?? 0) > 0 && <ul className="mt-3 space-y-1 text-xs text-caution">{d.odds!.red_flags.map((r) => <li key={r}>⚠ {r}</li>)}</ul>}
            <p className="mt-2 text-[11px] text-faint">A handful of past trades is not evidence; fewer than 5 caps the verdict at WATCH.</p>
          </Card>
          <Card title="In plain English"><p className="text-sm leading-relaxed">{(d.detail as SwingIdea["detail"]).narrative}</p></Card>
          <Narrator id={d.id} />
          {p && p.checklist.length > 0 && <Card title="Planner's checklist before you'd act"><ul className="list-disc space-y-1 pl-4 text-xs text-muted">{p.checklist.map((c) => <li key={c}>{c}</li>)}</ul></Card>}
        </div>
      </div>
    </div>
  );
}
