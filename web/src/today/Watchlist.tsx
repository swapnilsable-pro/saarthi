import { Fragment, useMemo, useState, type ReactNode } from "react";
import type { Today, WatchRow } from "../api";
import { inr } from "../api";
import { Card, EvidenceLink, Pill, SETUP_LABEL, Term } from "../ui";

type SortKey = "symbol" | "change_pct" | "turnover_cr" | "delivery_pct" | "rsi14";
const PAGE = 25;

export function Watchlist({ wl }: { wl: Today["watchlist"] }) {
  const [q, setQ] = useState("");
  const [setup, setSetup] = useState<string | null>(null);
  const [sort, setSort] = useState<{ k: SortKey | null; dir: 1 | -1 }>({ k: null, dir: -1 });
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<string | null>(null);

  const setups = useMemo(() => {
    const c: Record<string, number> = {};
    wl.rows.forEach((r) => r.setups.forEach((s) => (c[s] = (c[s] ?? 0) + 1)));
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [wl.rows]);

  const rows = useMemo(() => {
    const qq = q.trim().toUpperCase();
    let out = wl.rows.filter((r) =>
      (!setup || r.setups.includes(setup)) &&
      (!qq || r.symbol.includes(qq) || (r.name ?? "").toUpperCase().includes(qq)));
    if (sort.k) {
      const k = sort.k;
      out = [...out].sort((a, b) => {
        const av = a[k], bv = b[k];
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
      });
    }
    return out;
  }, [wl.rows, q, setup, sort]);

  const th = (k: SortKey, label: ReactNode, cls = "text-right") => (
    <th scope="col" className={`px-3 py-2 font-medium ${cls}`}
      aria-sort={sort.k === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button className="inline-flex items-center gap-1 hover:text-text"
        onClick={() => setSort((s) => ({ k, dir: s.k === k ? (s.dir === 1 ? -1 : 1) : k === "symbol" ? 1 : -1 }))}>
        {label}<span className="text-[10px]">{sort.k === k ? (sort.dir === 1 ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );

  return (
    <Card
      title={<>Watchlist <span className="ml-1 font-normal normal-case text-faint">· {wl.rows.length} setups from {inr.format(wl.scanned ?? 0)} stocks scanned · bhavcopy {wl.as_of ?? "–"}</span></>}
      right={<EvidenceLink runId={wl.run_id} label="Daily scan (nse-scanner/scan.py daily)" />}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} placeholder="Search symbol or company"
          aria-label="Search watchlist"
          className="h-8 w-56 rounded-md border border-line bg-panel px-2.5 text-sm placeholder:text-faint focus:border-accent focus:outline-none" />
        <button onClick={() => setSetup(null)} className={`h-8 rounded-md px-2.5 text-xs font-medium ${!setup ? "bg-accent-soft text-accent" : "text-muted hover:bg-panel-2"}`}>All</button>
        {setups.map(([s, n]) => (
          <button key={s} onClick={() => { setSetup(s); setLimit(PAGE); }}
            className={`h-8 rounded-md px-2.5 text-xs font-medium ${setup === s ? "bg-accent-soft text-accent" : "text-muted hover:bg-panel-2"}`}>
            <Term k={s}>{SETUP_LABEL[s] ?? s}</Term> <span className="num text-faint">{n}</span>
          </button>
        ))}
      </div>

      {wl.rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No watchlist yet. Run the evening scan to build one from the latest bhavcopy.</p>
      ) : (
        <div className="-mx-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-y border-line bg-panel-2 text-xs text-muted">
              <tr>
                {th("symbol", "Stock", "text-left")}
                <th scope="col" className="px-3 py-2 text-left font-medium">Setup</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Close ₹</th>
                {th("change_pct", "Day %")}
                {th("turnover_cr", <Term k="turnover">Turnover ₹cr</Term>)}
                {th("delivery_pct", <Term k="delivery">Delivery %</Term>)}
                {th("rsi14", <Term k="rsi">RSI</Term>)}
                <th scope="col" className="px-3 py-2 text-left font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, limit).map((r) => (
                <Fragment key={r.symbol}>
                  <tr className={`cursor-pointer border-b border-line hover:bg-panel-2 ${open === r.symbol ? "bg-panel-2" : ""}`}
                    onClick={() => setOpen(open === r.symbol ? null : r.symbol)}>
                    <td className="px-3 py-2">
                      <button className="text-left" aria-expanded={open === r.symbol} aria-label={`Details for ${r.symbol}`}>
                        <span className="font-semibold">{r.symbol}</span>
                        <span className="block max-w-[220px] truncate text-xs text-faint">{r.name}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{r.setups.map((s) => <Pill key={s} tone="accent">{SETUP_LABEL[s] ?? s}</Pill>)}</div></td>
                    <td className="px-3 py-2 text-right num">{inr.format(r.close)}</td>
                    <td className={`px-3 py-2 text-right num ${r.change_pct === null ? "" : r.change_pct >= 0 ? "text-go" : "text-stop"}`}>
                      {r.change_pct === null ? "–" : `${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(2)}`}
                    </td>
                    <td className="px-3 py-2 text-right num">{r.turnover_cr === null ? "–" : inr.format(r.turnover_cr)}</td>
                    <td className="px-3 py-2 text-right num">{r.delivery_pct?.toFixed(1) ?? "–"}</td>
                    <td className={`px-3 py-2 text-right num ${r.rsi14 !== null && r.rsi14 >= 70 ? "text-caution" : ""}`}>{r.rsi14?.toFixed(0) ?? "–"}</td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {r.flags.map((f) => <Pill key={f.text} tone={f.kind === "results" ? "caution" : "stop"}><Term k={f.kind}>{f.text}</Term></Pill>)}
                        {r.deals && <Pill tone="paper" title={r.deals.clients.join(", ")}>Deal ₹{inr.format(r.deals.net_value_cr)}cr</Pill>}
                        {r.filings.length > 0 && <Pill tone="neutral">{r.filings.length} filing{r.filings.length > 1 ? "s" : ""}</Pill>}
                      </div>
                    </td>
                  </tr>
                  {open === r.symbol && <Detail r={r} />}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > limit && (
        <button onClick={() => setLimit((l) => l + PAGE * 2)} className="mt-3 w-full rounded-md border border-line py-1.5 text-sm text-muted hover:bg-panel-2">
          Show more ({rows.length - limit} left)
        </button>
      )}
      <p className="mt-3 text-[11px] text-faint">
        A watchlist is a list of candidates, not recommendations. Trade ideas (entry, stop, target, odds) arrive in Phase 2, once the opening range forms.
      </p>
    </Card>
  );
}

function Detail({ r }: { r: WatchRow }) {
  return (
    <tr className="border-b border-line bg-panel-2/60">
      <td colSpan={8} className="px-4 py-3">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">Why it is on the list</p>
            <ul className="space-y-0.5 text-sm">
              {r.setups.map((s) => <li key={s}>{SETUP_LABEL[s] ?? s}: <span className="text-muted">{GLOSS[s] ?? ""}</span></li>)}
            </ul>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">Deals and filings</p>
            {r.deals ? <p className="text-sm">Net ₹{inr.format(r.deals.net_value_cr)} cr by {r.deals.clients.join(", ")}</p> : <p className="text-sm text-muted">No bulk/block deal.</p>}
            {r.filings.map((f) => (
              <p key={f.time + f.text} className="mt-1 text-xs text-muted">
                <span className="num">{f.time.replace("T", " ").slice(0, 16)}</span> · {f.category}{" "}
                {f.url && <a href={f.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">filing</a>}
              </p>
            ))}
          </div>
          <div>
            <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">Evidence</p>
            <div className="flex flex-wrap gap-1.5">
              <EvidenceLink runId={r.evidence.daily} label={`Daily scan · ${r.symbol}`}>scan</EvidenceLink>
              <EvidenceLink runId={r.evidence.bands} label="Price bands and ASM">bands</EvidenceLink>
              <EvidenceLink runId={r.evidence.deals} label="Bulk and block deals">deals</EvidenceLink>
              <EvidenceLink runId={r.evidence.results} label="Results calendar">results</EvidenceLink>
              <EvidenceLink runId={r.evidence.news} label="NSE announcements">filings</EvidenceLink>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

const GLOSS: Record<string, string> = {
  breakout_20d: "closed above its highest close of the last 20 sessions",
  oversold_bounce: "bounced from a deeply oversold RSI",
  reclaim_ma20: "closed back above its 20-day average",
  oversold: "RSI deeply oversold",
  bull_flag: "tight pause after a sharp rise",
};
