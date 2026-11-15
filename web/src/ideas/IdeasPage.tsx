import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ideasApi, inr, type IdeaSummary, type Mode, type ScanResult, type Verdict } from "../api";
import { Card, Pill, Skeleton, Term } from "../ui";
import { VERDICT_CLS, VERDICT_ICON, VERDICT_TONE } from "./IdeaDetail";

const DEMO_TIMES = ["09:35", "09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "14:00", "14:30"];
const sgn = (v: number) => `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(Math.round(v)))}`;

export function IdeasPage({ mode, open }: { mode: Mode; open: (id: string) => void }) {
  const qc = useQueryClient();
  const [at, setAt] = useState("09:45");
  const [filter, setFilter] = useState<Verdict | "ALL">("ALL");
  const list = useQuery({ queryKey: ["ideas", mode], queryFn: () => ideasApi.list(mode), refetchInterval: mode === "live" ? 60_000 : false });
  const scan = useMutation({
    mutationFn: () => ideasApi.scan(mode, mode === "demo" ? at : undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ideas", mode] }),
  });

  const ideas = (list.data?.ideas ?? []).filter((i) => filter === "ALL" || i.verdict === filter);
  const counts = (v: Verdict) => (list.data?.ideas ?? []).filter((i) => i.verdict === v).length;

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel p-4">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="min-w-[260px] flex-1">
            <h1 className="text-base font-semibold">Trade ideas · <Term k="orb">opening-range breakouts</Term></h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">
              After each 5-minute bar the scanner looks for a close above the first 15 minutes' high. Every breakout becomes an idea:
              a plan (entry, stop, target, size), its odds from 10,000 simulated sessions, the best time to enter, and a verdict.
              {mode === "live" ? " The scheduler does this automatically in the entry window; you can also scan now." : " Demo: replay Mon 9 Nov 2026 at any time."}
            </p>
          </div>
          <div className="flex items-end gap-2">
            {mode === "demo" && (
              <label className="text-xs text-muted">Scan as of (IST)
                <select value={at} onChange={(e) => setAt(e.target.value)}
                  className="mt-1 block h-9 rounded-md border border-line bg-panel px-2 text-sm text-text">
                  {DEMO_TIMES.map((t) => <option key={t}>{t}</option>)}
                </select>
              </label>
            )}
            <button onClick={() => scan.mutate()} disabled={scan.isPending}
              className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60">
              {scan.isPending ? "Scanning…" : "Scan for breakouts"}
            </button>
          </div>
        </div>
        {scan.data && <ScanReport r={scan.data} />}
        {scan.error && <p className="mt-3 text-sm text-stop">{(scan.error as Error).message}</p>}
      </section>

      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by verdict">
        {(["ALL", "TAKE", "WATCH", "SKIP"] as const).map((v) => (
          <button key={v} role="tab" aria-selected={filter === v} onClick={() => setFilter(v)}
            className={`rounded-md px-3 py-1.5 text-sm ${filter === v ? "bg-panel font-semibold shadow-sm ring-1 ring-line" : "text-muted"}`}>
            {v === "ALL" ? `All ${list.data?.ideas.length ?? ""}` : `${VERDICT_ICON[v]} ${v} ${counts(v)}`}
          </button>
        ))}
      </div>

      {list.isLoading && <Skeleton h={160} />}
      {list.data && ideas.length === 0 && (
        <Card><p className="py-6 text-center text-sm text-muted">
          {list.data.ideas.length ? "Nothing with this verdict." :
            mode === "demo" ? "No ideas yet. Pick a time and scan the demo session." :
              "No ideas yet today. Ideas appear after 09:30, once the opening range is set and a stock breaks out of it."}
        </p></Card>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
        {ideas.map((i) => <IdeaCard key={i.id} i={i} open={open} />)}
      </div>
    </div>
  );
}

function IdeaCard({ i, open }: { i: IdeaSummary; open: (id: string) => void }) {
  const vc = VERDICT_CLS[i.verdict];
  const p = i.plan, o = i.odds;
  return (
    <button onClick={() => open(i.id)} className="rounded-xl border border-line bg-panel p-4 text-left transition hover:border-accent focus-visible:border-accent">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold">{i.symbol}</span>
            {i.synthetic && <Pill tone="paper">synthetic</Pill>}
            <span className="text-xs text-muted num">{i.session_day} · {i.decided_at} IST</span>
          </div>
          {i.name && <p className="truncate text-xs text-faint">{i.name}</p>}
        </div>
        <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-bold ${vc.soft} ${vc.text}`}>
          {VERDICT_ICON[i.verdict]} {i.verdict} <span className="font-normal opacity-80">{Math.round(i.score)}</span>
        </span>
      </div>
      {p && (
        <dl className="mt-3 grid grid-cols-4 gap-2 text-sm num">
          <div><dt className="text-[11px] text-faint">Entry</dt><dd className="font-medium">{p.entry.toFixed(2)}</dd></div>
          <div><dt className="text-[11px] text-faint">Stop</dt><dd className="font-medium text-stop">{p.stop.toFixed(2)}</dd></div>
          <div><dt className="text-[11px] text-faint">Target</dt><dd className="font-medium text-go">{p.target.toFixed(2)}</dd></div>
          <div><dt className="text-[11px] text-faint">Qty</dt><dd className="font-medium">{inr.format(p.qty)}</dd></div>
        </dl>
      )}
      {o && (
        <p className="mt-2 text-xs text-muted num">
          Target first {Math.round(o.p_target * 100)}% · net R:R {o.net_rr.toFixed(2)} ·{" "}
          <span className={o.net_per_trade >= 0 ? "text-go" : "text-stop"}>{sgn(o.net_per_trade)}/trade</span>
          {p?.best_window?.from && <> · enter {p.best_window.from}–{p.best_window.to}</>}
        </p>
      )}
      <p className={`mt-2 line-clamp-2 text-xs ${i.verdict === "TAKE" ? "text-muted" : vc.text}`}>{i.reason}</p>
      <span className="sr-only">Verdict tone {VERDICT_TONE[i.verdict]}</span>
    </button>
  );
}

function ScanReport({ r }: { r: ScanResult }) {
  return (
    <div className="mt-3 rounded-lg bg-panel-2 p-3 text-sm">
      {r.error ? <p className="text-stop">{r.error}</p> : (
        <p>
          Scanned <b>{r.scanned.length}</b> stock{r.scanned.length === 1 ? "" : "s"} at <b className="num">{r.as_of.slice(11)}</b> IST:{" "}
          {r.breakouts.length ? <>{r.breakouts.length} breakout{r.breakouts.length > 1 ? "s" : ""} ({r.breakouts.map((b) => `${b.symbol} ${b.at}`).join(", ")})</> : "no breakouts yet"}
          {r.decisions.length > 0 && <> · <b>{r.decisions.length}</b> new idea{r.decisions.length > 1 ? "s" : ""}</>}
          {r.already_decided && r.already_decided.length > 0 && <span className="text-muted"> · already decided: {r.already_decided.join(", ")}</span>}
        </p>
      )}
      {r.errors.length > 0 && (
        <details className="mt-1 text-xs text-muted"><summary className="cursor-pointer">{r.errors.length} symbol note{r.errors.length > 1 ? "s" : ""}</summary>
          <ul className="mt-1 space-y-0.5">{r.errors.map((e, k) => <li key={k}><b>{e.symbol}</b>: {e.why}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
