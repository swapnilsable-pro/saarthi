import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { perfApi, type Book, type Group, type Mode, type Performance } from "../api";
import { Card, Skeleton } from "../ui";
import { CalibrationChart, ChartFrame, DivergingBars, EquityCurve, Legend, money, RHistogram, Swatch } from "./charts";
import { ReplayCard } from "./HistoryPage";

const BOOK_LABEL: Record<Book, { title: string; help: string }> = {
  all: { title: "Every idea, as planned", help: "Ghost book: each idea (TAKE, WATCH or SKIP) traded exactly as planned. Hindsight, for judging the system." },
  take: { title: "Every TAKE, as planned", help: "Ghost book: only the ideas the verdict said to take. This is what following Saarthi to the letter would have done." },
  mine: { title: "Your paper trades", help: "The trades you placed on the Paper Desk." },
};

export function PerformancePage({ mode }: { mode: Mode }) {
  const [book, setBook] = useState<Book>("all");
  const q = useQuery({ queryKey: ["perf", mode, book], queryFn: () => perfApi.performance(mode, book) });
  const p = q.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Which book">
        {(["all", "take", "mine"] as Book[]).map((b) => (
          <button key={b} role="tab" aria-selected={book === b} onClick={() => setBook(b)}
            className={`rounded-md px-3 py-1.5 text-sm ${book === b ? "bg-panel font-semibold shadow-sm ring-1 ring-line" : "text-muted"}`}>
            {BOOK_LABEL[b].title} <span className="text-faint num">{p?.books[b] ?? ""}</span>
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">{BOOK_LABEL[book].help}</p>

      {q.isLoading || !p ? <Skeleton h={300} /> : p.stats.empty ? (
        <>
          <Card><p className="py-6 text-center text-sm text-muted">
            {book === "take" ? "No TAKE ideas yet, so nothing to show here. Every idea so far failed at least one check (see the check report below)."
              : book === "mine" ? "You have no closed paper trades yet. Place one from an idea on the Paper Desk."
                : "No closed ghost trades yet. Replay past sessions to fill this in."}
          </p></Card>
          {book !== "all" && <BelowCharts p={p} />}
          {p.books.all === 0 && <ReplayCard mode={mode} />}
        </>
      ) : (
        <>
          <Kpis p={p} />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <ChartFrame title="Cumulative net P&L" subtitle={`${p.stats.trades} trades over ${p.stats.sessions} sessions, after costs`}
              table={<Table head={["#", "Exit", "Stock", "Trade", "Cumulative"]} rows={(p.stats.equity_curve ?? []).map((c, i) => [i + 1, c.t, c.symbol, money(c.net), money(c.equity)])} />}>
              <EquityCurve points={p.stats.equity_curve ?? []} />
            </ChartFrame>
            <ChartFrame title="Trade results in R" subtitle="Each trade's net P&L divided by its planned risk"
              legend={<Legend items={[{ label: "loss", swatch: <Swatch color="var(--viz-neg)" /> }, { label: "gain", swatch: <Swatch color="var(--viz-pos)" /> }]} />}
              table={<Table head={["R range", "Trades"]} rows={(p.stats.r_histogram ?? []).map((b) => [b.from === null ? `< ${b.to}` : b.to === null ? `≥ ${b.from}` : `${b.from} to ${b.to}`, b.n])} />}>
              <RHistogram bins={p.stats.r_histogram ?? []} />
            </ChartFrame>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2 xl:grid-cols-3">
            <Breakdown title="By entry time" rows={p.stats.by_entry_hour ?? []} />
            <Breakdown title="By weekday" rows={p.stats.by_weekday ?? []} />
            <Breakdown title="By how it ended" rows={(p.stats.by_exit ?? []).map((g) => ({ ...g, key: g.key.toLowerCase().replace("_", " ") }))} />
            {(p.stats.by_regime?.length ?? 0) > 0 && <Breakdown title="By market regime" rows={p.stats.by_regime ?? []} />}
            {(p.stats.by_verdict?.length ?? 0) > 0 && <Breakdown title="By verdict" rows={p.stats.by_verdict ?? []} />}
            {(p.stats.followed_plan?.length ?? 0) > 0 && <Breakdown title="Plan adherence" rows={p.stats.followed_plan ?? []} />}
          </div>
          <BelowCharts p={p} />
        </>
      )}
    </div>
  );
}

function Kpis({ p }: { p: Performance }) {
  const s = p.stats;
  const tiles: [string, string, string?][] = [
    ["Net P&L", money(s.net ?? 0), `${s.trades} trades`],
    ["Expectancy", money(s.expectancy ?? 0), `${s.avg_r?.toFixed(2) ?? "–"}R a trade`],
    ["Win rate", `${Math.round((s.win_rate ?? 0) * 100)}%`, `avg win ${money(s.avg_win ?? 0)} · loss ${money(s.avg_loss ?? 0)}`],
    ["Profit factor", s.profit_factor?.toFixed(2) ?? "–", "gross wins ÷ gross losses"],
    ["Max drawdown", money(s.max_drawdown ?? 0), "worst peak-to-trough"],
    ["Costs", `${s.costs_pct_of_gross ?? "–"}%`, `of gross P&L · ${money(-(s.costs_total ?? 0))}`],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {tiles.map(([k, v, sub]) => (
        <div key={k} className="rounded-xl border border-line bg-panel px-4 py-3">
          <p className="text-xs text-faint">{k}</p>
          <p className="mt-0.5 text-xl font-semibold num">{v}</p>
          {sub && <p className="text-[11px] text-muted num">{sub}</p>}
        </div>
      ))}
      <p className="col-span-full text-[11px] text-faint num">
        Average worst move against {s.avg_mae_r?.toFixed(2)}R, best move for {s.avg_mfe_r?.toFixed(2)}R while in the trade.
        {s.trades < 30 && <b className="text-caution"> {s.trades} trades is a small sample: treat every number here as a rough guide.</b>}
      </p>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: Group[] }) {
  return (
    <ChartFrame title={title} table={<Table head={["", "Trades", "Win %", "Avg R", "Net"]} rows={rows.map((g) => [g.key, g.n, `${Math.round(g.win_rate * 100)}%`, g.avg_r?.toFixed(2) ?? "–", money(g.net)])} />}>
      <DivergingBars rows={rows.map((g) => ({ key: g.key, label: <>{g.key} <span className="text-xs text-faint">· {g.n}</span></>, value: g.net,
        note: `${g.avg_r?.toFixed(2) ?? "–"}R avg` }))} />
    </ChartFrame>
  );
}

function BelowCharts({ p }: { p: Performance }) {
  const c = p.calibration;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-2">
      <ChartFrame title="Was the Time Machine honest?" subtitle={`${c.n} ghost trades traded exactly like the model (stop vs target, flat at 15:15, no trail)`}
        table={<Table head={["Predicted", "Avg prediction", "Actually hit", "Trades"]} rows={c.buckets.map((b) => [`${Math.round(b.from * 100)}–${Math.round(b.to * 100)}%`, `${Math.round(b.predicted * 100)}%`, `${Math.round(b.observed * 100)}%`, b.n])} />}>
        {c.n === 0 ? <p className="text-sm text-muted">No ghost outcomes yet.</p> : (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-[minmax(0,1fr)_200px]">
            <CalibrationChart buckets={c.buckets} n={c.n} />
            <div className="space-y-2 text-sm">
              <p className="rounded-lg bg-panel-2 p-2.5">{c.verdict}</p>
              <dl className="grid grid-cols-[1fr_auto] gap-y-1 text-xs num">
                <dt className="text-muted">Predicted hit rate</dt><dd>{Math.round((c.mean_predicted ?? 0) * 100)}%</dd>
                <dt className="text-muted">Actual hit rate</dt><dd>{Math.round((c.mean_observed ?? 0) * 100)}% ± {Math.round(2 * (c.gap_se ?? 0) * 100)}</dd>
                <dt className="text-muted">Predicted net / trade</dt><dd>{money(c.predicted_net_avg ?? 0)}</dd>
                <dt className="text-muted">Actual net / trade</dt><dd>{money(c.realized_net_avg ?? 0)}</dd>
                <dt className="text-muted" title="Mean squared error of the probabilities; lower is better">Brier score</dt><dd>{c.brier?.toFixed(3)}</dd>
                <dt className="text-muted" title="Brier score of always predicting the overall hit rate">…if it always guessed the average</dt><dd>{c.brier_reference?.toFixed(3)}</dd>
              </dl>
            </div>
          </div>
        )}
      </ChartFrame>
      <ChartFrame title="What each check saved or cost"
        subtitle="Ghost P&L of the ideas each check stopped (by the first check they failed). Negative = the check kept you out of losers."
        table={<Table head={["Check", "Ideas", "Ghost net", "Avg R", "Effect"]} rows={p.gates.rows.map((r) => [r.label, r.n, money(r.ghost_net), r.avg_r?.toFixed(2) ?? "–", r.effect ?? "taken"])} />}>
        {p.gates.rows.length === 0 ? <p className="text-sm text-muted">No ghost outcomes yet.</p> : (
          <>
            <DivergingBars rows={p.gates.rows.map((r) => ({
              key: r.gate, value: r.ghost_net,
              label: <>{r.gate === "PASSED" ? "" : <span className="mr-1 font-mono text-[11px] text-faint">{r.gate}</span>}{r.label} <span className="text-xs text-faint">· {r.n}</span></>,
              note: r.effect === "saved" ? "saved you this" : r.effect === "cost" ? "missed this" : "taken",
            }))} />
            <p className="mt-3 text-[11px] text-faint">A check that "missed" money on a small sample is not necessarily wrong. Look again after 50+ ideas.</p>
          </>
        )}
      </ChartFrame>
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="w-full text-sm num">
      <thead className="sticky top-0 bg-panel text-xs text-muted"><tr>{head.map((h, i) => <th key={i} className={`py-1 font-medium ${i ? "text-right" : "text-left"}`}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-line">{r.map((c, k) => <td key={k} className={`py-1 ${k ? "text-right" : ""}`}>{c}</td>)}</tr>)}</tbody>
    </table>
  );
}
