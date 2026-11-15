import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { barsApi, inr, paperApi, type AccountState, type Mode, type PaperTrade, type Ticket } from "../api";
import { Card, Pill, Skeleton, Term } from "../ui";
import { DailyChart } from "../swing/DailyChart";
import { swingApi } from "../api";
import { TradeChart } from "./TradeChart";

const sgn = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(Math.round(v)))}`;
const STATUS_TONE = { working: "accent", open: "paper", closed: "neutral", cancelled: "neutral", rejected: "stop", expired: "neutral" } as const;
const EXIT_TEXT: Record<string, string> = {
  STOP: "Stopped out", BREAKEVEN_STOP: "Breakeven stop", TARGET: "Target hit", SQUARE_OFF: "Squared off 15:15",
  MANUAL: "Closed by you", DATA_END: "Data ended", TIME_EXIT: "Time exit (max hold)",
};

export function PaperDesk({ mode, ideaId, clearIdea }: { mode: Mode; ideaId: string | null; clearIdea: () => void }) {
  const acc = useQuery({ queryKey: ["paper-account", mode], queryFn: () => paperApi.account(mode), refetchInterval: mode === "live" ? 30_000 : false });
  const trades = useQuery({ queryKey: ["paper-trades", mode], queryFn: () => paperApi.trades(mode), refetchInterval: mode === "live" ? 30_000 : false });

  return (
    <div className="space-y-4">
      {acc.data ? <AccountBar a={acc.data} mode={mode} /> : <Skeleton h={88} />}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[400px_minmax(0,1fr)]">
        <TicketPanel mode={mode} ideaId={ideaId} clearIdea={clearIdea} />
        <Card title={<>Paper trades <span className="font-normal normal-case text-faint">· {trades.data?.trades.length ?? 0}</span></>}>
          {trades.isLoading ? <Skeleton h={160} /> : <TradeTable mode={mode} trades={trades.data?.trades ?? []} />}
        </Card>
      </div>
    </div>
  );
}

function AccountBar({ a, mode }: { a: AccountState; mode: Mode }) {
  const used = Math.min(1, Math.max(0, -a.day_net / a.daily_loss_cap));
  return (
    <section className="rounded-xl border border-paper/30 bg-panel px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <p className="text-xs text-faint">{a.account.name} · session {a.session_day}{mode === "demo" && " (demo)"}</p>
          <p className="text-xl font-semibold num">₹{inr.format(a.equity)}</p>
        </div>
        <Stat label="Today, realised" value={sgn(a.day_net)} tone={a.day_net >= 0 ? "text-go" : "text-stop"} />
        {a.day_unrealized !== 0 && <Stat label="Open, unrealised" value={sgn(a.day_unrealized)} tone={a.day_unrealized >= 0 ? "text-go" : "text-stop"} />}
        <Stat label="Risk in open trades" value={`₹${inr.format(Math.round(a.risk_open))}`} />
        <div className="min-w-[180px]">
          <p className="text-xs text-faint">Daily loss used · cap ₹{inr.format(Math.round(a.daily_loss_cap))}</p>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-panel-2" role="meter" aria-valuenow={Math.round(used * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Daily loss cap used">
            <div className={`h-full ${used > 0.75 ? "bg-stop" : used > 0.4 ? "bg-caution" : "bg-go"}`} style={{ width: `${used * 100}%` }} />
          </div>
        </div>
        <Stat label="Trades left today" value={`${a.trades_left} of ${a.account.settings.max_trades_per_day}`} />
      </div>
      {a.locked && <p className="mt-2 rounded-md bg-stop-soft px-3 py-2 text-sm text-stop">🔒 {a.locked}</p>}
    </section>
  );
}

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return <div><p className="text-xs text-faint">{label}</p><p className={`text-base font-semibold num ${tone}`}>{value}</p></div>;
}

// ------------------------------------------------------------------------------- ticket
const EMPTY: Partial<Ticket> = { entry_type: "LIMIT", trail_breakeven: true };

function TicketPanel({ mode, ideaId, clearIdea }: { mode: Mode; ideaId: string | null; clearIdea: () => void }) {
  const qc = useQueryClient();
  const [t, setT] = useState<Partial<Ticket>>(EMPTY);
  const [debounced, setDebounced] = useState<Partial<Ticket>>(EMPTY);

  // Prefill from the idea once.
  const seed = useQuery({
    queryKey: ["ticket-seed", ideaId], enabled: !!ideaId,
    queryFn: () => paperApi.preview({ mode, idea_id: ideaId! }),
  });
  useEffect(() => { if (seed.data) { setT(seed.data.ticket); setDebounced(seed.data.ticket); } }, [seed.data]);
  useEffect(() => { const h = setTimeout(() => setDebounced(t), 300); return () => clearTimeout(h); }, [t]);

  const ready = !!(debounced.symbol && debounced.qty && debounced.stop && (debounced.entry_type === "MARKET" || debounced.entry_price));
  const pv = useQuery({
    queryKey: ["preview", mode, ideaId, debounced], enabled: ready,
    queryFn: () => paperApi.preview({ mode, ...(ideaId ? { idea_id: ideaId } : {}), ...debounced }),
  });
  const place = useMutation({
    mutationFn: () => paperApi.place({ mode, ...(ideaId ? { idea_id: ideaId } : {}), ...t }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-trades", mode] });
      qc.invalidateQueries({ queryKey: ["paper-account", mode] });
      qc.invalidateQueries({ queryKey: ["preview"] });
    },
  });

  const num = (k: keyof Ticket) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setT((x) => ({ ...x, [k]: e.target.value === "" ? null : Number(e.target.value) }));
  const p = pv.data;
  const fromIdea = !!ideaId && !!seed.data;

  return (
    <Card title="Order ticket" right={<span className="text-[11px] font-semibold text-paper">PAPER</span>}>
      {fromIdea && (
        <div className="mb-3 flex items-center justify-between rounded-md bg-accent-soft px-3 py-2 text-xs text-accent">
          <span>Prefilled from the {seed.data!.ticket.symbol} idea's plan</span>
          <button onClick={() => { clearIdea(); setT(EMPTY); }} className="underline">clear</button>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <Field label="Stock">
          <input value={t.symbol ?? ""} onChange={(e) => setT((x) => ({ ...x, symbol: e.target.value.toUpperCase() }))}
            placeholder="e.g. RELIANCE" className="inp" aria-label="Stock symbol" />
        </Field>
        <Field label="Quantity"><input type="number" min={1} value={t.qty ?? ""} onChange={num("qty")} className="inp num" aria-label="Quantity" /></Field>
        <Field label="Entry type">
          <select value={t.entry_type} onChange={(e) => setT((x) => ({ ...x, entry_type: e.target.value as Ticket["entry_type"] }))} className="inp" aria-label="Entry order type">
            <option value="LIMIT">Limit</option><option value="SL-M">Stop-market (buy-stop)</option><option value="MARKET">Market</option>
          </select>
        </Field>
        <Field label={t.entry_type === "SL-M" ? "Trigger ₹" : "Limit ₹"}>
          <input type="number" step="0.05" disabled={t.entry_type === "MARKET"} value={t.entry_type === "MARKET" ? "" : t.entry_price ?? ""}
            onChange={num("entry_price")} className="inp num disabled:opacity-40" aria-label="Entry price" />
        </Field>
        <Field label="Stop ₹"><input type="number" step="0.05" value={t.stop ?? ""} onChange={num("stop")} className="inp num" aria-label="Stop price" /></Field>
        <Field label="Target ₹"><input type="number" step="0.05" value={t.target ?? ""} onChange={num("target")} className="inp num" aria-label="Target price" /></Field>
        <Field label={mode === "demo" ? "Placed at (demo clock)" : "Placed at"}>
          <input value={t.placed_at ?? ""} onChange={(e) => setT((x) => ({ ...x, placed_at: e.target.value }))}
            placeholder={mode === "live" ? "now" : "2026-11-09 09:40"} className="inp num" aria-label="Placed at, IST" />
        </Field>
        <label className="flex items-end gap-2 pb-2 text-xs text-muted">
          <input type="checkbox" checked={t.trail_breakeven ?? true} onChange={(e) => setT((x) => ({ ...x, trail_breakeven: e.target.checked }))} className="accent-[var(--accent)]" />
          Move stop to breakeven at +1R
        </label>
      </div>

      <div className="mt-4 rounded-lg bg-panel-2 p-3 text-sm">
        {!ready ? <p className="text-muted">Fill in the stock, quantity, entry and stop to see the risk.</p>
          : pv.isLoading ? <p className="text-muted">Checking…</p>
          : p ? (
            <>
              {p.reject_reason
                ? <p className="text-stop"><b>Would be rejected:</b> {p.reject_reason}</p>
                : <p className="text-go">✓ Passes the account's rules.</p>}
              <dl className="mt-2 grid grid-cols-2 gap-y-1 num">
                <dt className="text-muted">Position value</dt><dd className="text-right">₹{inr.format(Math.round(p.position_value))}</dd>
                <dt className="text-muted">Risk at stop</dt><dd className="text-right">₹{inr.format(Math.round(p.risk))} <span className="text-faint">({p.risk_pct_of_capital.toFixed(2)}%)</span></dd>
                {p.estimates.at_stop && <><dt className="text-muted">If stopped, after costs</dt><dd className="text-right text-stop">{sgn(p.estimates.at_stop.net)}</dd></>}
                {p.estimates.at_target && <><dt className="text-muted">If target, after costs</dt><dd className="text-right text-go">{sgn(p.estimates.at_target.net)}</dd></>}
                <dt className="text-muted">Tick size</dt><dd className="text-right">₹{p.tick}</dd>
              </dl>
            </>
          ) : pv.error ? <p className="text-stop">{(pv.error as Error).message.replace(/^\d+ /, "")}</p> : null}
      </div>

      <button onClick={() => place.mutate()} disabled={!ready || place.isPending}
        className="mt-4 w-full rounded-lg bg-paper py-2.5 text-sm font-semibold text-white disabled:opacity-50">
        {place.isPending ? "Placing…" : "Place PAPER order"}
      </button>
      <p className="mt-2 text-center text-[11px] text-faint">
        Simulated exchange only. {mode === "demo" ? "Demo sessions are history, so the trade plays out instantly, bar by bar." : "Fills update as each 5-minute bar completes."}
      </p>
      {place.data && <p className="mt-2 text-sm">{place.data.status === "rejected" ? <span className="text-stop">Rejected: {place.data.reject_reason}</span>
        : <>Placed: <b>{place.data.symbol}</b> is <b>{place.data.status}</b>{place.data.exit_reason && <> · {EXIT_TEXT[place.data.exit_reason]} · <b className={(place.data.net_pnl ?? 0) >= 0 ? "text-go" : "text-stop"}>{sgn(place.data.net_pnl)}</b></>}</>}</p>}
      <style>{`.inp{display:block;width:100%;height:2.25rem;border-radius:.375rem;border:1px solid var(--line);background:var(--panel);padding:0 .625rem;color:var(--text)} .inp:focus{outline:none;border-color:var(--accent)}`}</style>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-xs text-muted">{label}<div className="mt-1">{children}</div></label>;
}

// ------------------------------------------------------------------------------- trades
function TradeTable({ trades, mode }: { trades: PaperTrade[]; mode: Mode }) {
  const [open, setOpen] = useState<string | null>(null);
  const qc = useQueryClient();
  const cancel = useMutation({
    mutationFn: (id: string) => paperApi.cancel(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["paper-trades", mode] }); qc.invalidateQueries({ queryKey: ["paper-account", mode] }); },
  });
  if (!trades.length) return <p className="py-8 text-center text-sm text-muted">No paper trades yet. Open an idea and press "Paper trade", or fill in the ticket.</p>;
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm num">
        <thead className="border-y border-line bg-panel-2 text-xs text-muted">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Stock</th><th className="px-3 py-2 text-left font-medium">Status</th>
            <th className="px-3 py-2 text-right font-medium">Bought</th><th className="px-3 py-2 text-right font-medium">Sold</th>
            <th className="px-3 py-2 text-left font-medium">Exit</th><th className="px-3 py-2 text-right font-medium">Net P&L</th>
            <th className="px-3 py-2 text-right font-medium"><span title="Net P&L divided by the planned risk">R</span></th>
            <th className="px-3 py-2 text-right font-medium"><span title="Worst and best excursion while in the trade, in R">MAE / MFE</span></th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <Fragment key={t.id}>
              <tr onClick={() => setOpen(open === t.id ? null : t.id)} className={`cursor-pointer border-b border-line hover:bg-panel-2 ${open === t.id ? "bg-panel-2" : ""}`}>
                <td className="px-3 py-2"><b>{t.symbol}</b> <span className="text-xs text-faint">{t.qty} · {t.session_day.slice(5)} {(t.order_spec as unknown as { kind?: string }).kind === "gtt" ? "GTT · CNC" : t.order_spec.placed_at?.slice(11)}</span>
                  {t.followed_plan === 1 && <span className="ml-1 text-[10px] text-accent" title="Placed exactly as the idea planned">plan</span>}</td>
                <td className="px-3 py-2"><Pill tone={STATUS_TONE[t.status]}>{t.status}</Pill></td>
                <td className="px-3 py-2 text-right">{t.entry_price?.toFixed(2) ?? "–"}<span className="block text-[10px] text-faint">{t.entry_at?.slice(11)}</span></td>
                <td className="px-3 py-2 text-right">{t.exit_price?.toFixed(2) ?? (t.result?.last_price ? <span className="text-faint">{t.result.last_price.toFixed(2)} now</span> : "–")}<span className="block text-[10px] text-faint">{t.exit_at?.slice(11)}</span></td>
                <td className="px-3 py-2 text-xs">{t.exit_reason ? EXIT_TEXT[t.exit_reason] : t.reject_reason ? <span className="text-stop">{t.reject_reason}</span> : t.status === "open" ? `stop ${t.result?.stop_now?.toFixed(2)}` : ""}</td>
                <td className={`px-3 py-2 text-right font-semibold ${(t.net_pnl ?? t.result?.unrealized_pnl ?? 0) >= 0 ? "text-go" : "text-stop"}`}>
                  {t.net_pnl !== null ? sgn(t.net_pnl) : t.result?.unrealized_pnl != null ? <span className="font-normal">{sgn(t.result.unrealized_pnl)}*</span> : "–"}
                </td>
                <td className="px-3 py-2 text-right">{t.r_multiple?.toFixed(2) ?? "–"}</td>
                <td className="px-3 py-2 text-right text-xs">{t.mae_r !== null ? `${t.mae_r.toFixed(2)} / ${t.mfe_r?.toFixed(2)}` : "–"}</td>
              </tr>
              {open === t.id && (
                <tr className="border-b border-line"><td colSpan={8} className="px-4 py-3"><TradeDetail t={t} onCancel={() => cancel.mutate(t.id)} busy={cancel.isPending} /></td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      <p className="mt-2 px-4 text-[11px] text-faint">* unrealised. R is net P&L over the planned risk. <Term k="square_off">Square-off</Term> closes intraday trades at 15:15.</p>
    </div>
  );
}

function GttChart({ t }: { t: PaperTrade }) {
  const o = t.order_spec as unknown as { trigger: number; stop: number; target: number | null };
  const b = useQuery({ queryKey: ["daily", t.data_mode, t.symbol, "full"], queryFn: () => swingApi.daily(t.data_mode, t.symbol) });
  const bars = (b.data?.bars ?? []).slice(-80);
  return bars.length ? <DailyChart bars={bars} height={280}
    levels={[{ price: o.trigger, title: "GTT", tone: "entry" }, { price: o.stop, title: "Stop", tone: "stop" }, ...(o.target ? [{ price: o.target, title: "Target", tone: "target" as const }] : [])]}
    marks={[{ date: t.session_day, text: "placed", tone: "muted", above: true },
      ...(t.entry_at ? [{ date: t.entry_at, text: `Buy ${t.entry_price?.toFixed(2)}`, tone: "entry" as const }] : []),
      ...(t.exit_at ? [{ date: t.exit_at, text: `Sell ${t.exit_price?.toFixed(2)}`, tone: "exit" as const, above: true }] : [])]} /> : <Skeleton h={280} />;
}

function TradeDetail({ t, onCancel, busy }: { t: PaperTrade; onCancel: () => void; busy: boolean }) {
  const isGtt = (t.order_spec as unknown as { kind?: string }).kind === "gtt";
  const b = useQuery({ queryKey: ["bars", t.data_mode, t.symbol, t.session_day, t.status], enabled: !isGtt, queryFn: () => barsApi.session(t.data_mode, t.symbol, t.session_day) });
  const legs = t.costs ? Object.entries(t.costs.legs).filter(([, v]) => v > 0.005) : [];
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div>{isGtt ? <GttChart t={t} /> : b.data?.bars.length ? <TradeChart bars={b.data.bars} trade={t} /> : <Skeleton h={280} />}</div>
      <div className="space-y-3 text-sm">
        <div>
          <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">What happened</p>
          <ol className="space-y-1">
            {(t.result?.events ?? []).map((e, i) => <li key={i} className="flex gap-2"><span className="text-xs text-faint num">{e.time.slice(11)}</span><span>{e.text}</span></li>)}
            {t.status === "rejected" && <li className="text-stop">{t.reject_reason}</li>}
          </ol>
        </div>
        {t.costs && (
          <div>
            <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">Costs ₹{t.costs.total.toFixed(2)}</p>
            <p className="text-xs text-muted">{legs.map(([k, v]) => `${k.toUpperCase()} ${v.toFixed(2)}`).join(" · ")}</p>
            <p className="mt-1 text-xs">Gross {sgn(t.gross_pnl)} → net <b>{sgn(t.net_pnl)}</b></p>
          </div>
        )}
        {t.result?.slippage_vs_plan != null && <p className="text-xs text-muted">Entry vs plan: {t.result.slippage_vs_plan >= 0 ? "+" : ""}{t.result.slippage_vs_plan.toFixed(2)} a share</p>}
        {(t.ambiguous_bars ?? 0) > 0 && <p className="text-xs text-faint">{t.ambiguous_bars} bar(s) touched both levels; counted against you.</p>}
        {(t.status === "working" || t.status === "open") && (
          <button onClick={onCancel} disabled={busy} className="rounded-md border border-line px-3 py-1.5 text-xs hover:border-stop hover:text-stop">
            {t.status === "working" ? "Cancel order" : "Close at next bar's open"}
          </button>
        )}
      </div>
    </div>
  );
}
