import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { api, type JobView, type Mode } from "./api";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { PaperDesk } from "./desk/PaperDesk";
import { HistoryPage } from "./perf/HistoryPage";
import { PerformancePage } from "./perf/PerformancePage";
import { ReplayPage } from "./sim/ReplayPage";
import { SwingDetail, SwingList } from "./swing/Swing";
import { LearnPage } from "./learn/LearnPage";
import { Onboarding } from "./learn/Onboarding";
import { usePrefs } from "./prefs";
import { IdeaDetail } from "./ideas/IdeaDetail";
import { IdeasPage } from "./ideas/IdeasPage";
import { EventsCard } from "./today/EventsCard";
import { MoodCard } from "./today/MoodCard";
import { SessionRibbon } from "./today/SessionRibbon";
import { DealsCard, NewsCard, SectorsBreadth } from "./today/SidePanels";
import { Watchlist } from "./today/Watchlist";
import { EvidenceCtx, Pill, Skeleton } from "./ui";

const TABS = [
  { id: "today", label: "Today", phase: null },
  { id: "ideas", label: "Ideas", phase: null },
  { id: "desk", label: "Paper Desk", phase: null },
  { id: "history", label: "History", phase: null },
  { id: "performance", label: "Performance", phase: null },
  { id: "replay", label: "Replay", phase: null },
  { id: "learn", label: "Learn", phase: null },
];

function readMode(): Mode {
  try {
    const m = localStorage.getItem("saarthi.mode");
    return m === "live" ? "live" : "demo";
  } catch {
    return "demo";
  }
}

/** Tiny hash router: #/today, #/ideas, #/idea/<id>. */
function useRoute(): [string[], (path: string) => void] {
  const read = () => (window.location.hash.replace(/^#\/?/, "") || "today").split("/");
  const [route, setRoute] = useState<string[]>(read);
  useEffect(() => {
    const on = () => { setRoute(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [route, (path: string) => { window.location.hash = `/${path}`; }];
}

export default function App() {
  const [mode, setMode] = useState<Mode>(readMode);
  const [route, go] = useRoute();
  const { t: tr, lang, setLang, pro, setPro } = usePrefs();
  const [tour, setTour] = useState(false);
  const page = route[0] === "idea" || route[0] === "swing" ? "ideas" : route[0];
  const [evidence, setEvidence] = useState<{ runId: string; label: string } | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    try { localStorage.setItem("saarthi.mode", mode); } catch { /* storage unavailable */ }
  }, [mode]);

  const today = useQuery({ queryKey: ["today", mode], queryFn: () => api.today(mode), refetchInterval: 60_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 300_000 });

  const job = useMutation({
    mutationFn: (name: string) => api.runJob(name, mode),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today", mode] }),
  });

  useEffect(() => setEvidence(null), [route.join("/")]);   // a new page closes the evidence drawer
  const openEvidence = useCallback((runId: string, label: string) => setEvidence({ runId, label }), []);
  const closeEvidence = useCallback(() => setEvidence(null), []);
  const t = today.data;
  const empty = t && !t.jobs.evening_scan && !t.jobs.premarket_brief;

  return (
    <EvidenceCtx.Provider value={openEvidence}>
      <div className="min-h-screen">
        {/* ------------------------------------------------------------ header */}
        <header className="sticky top-0 z-30 border-b border-line bg-panel/95 backdrop-blur">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 md:px-6">
            <div className="flex items-center gap-2">
              <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="7" fill="var(--accent)" /><path d="M7 21l6-7 5 4 7-9" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="text-[15px] font-semibold tracking-tight">Saarthi</span>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-paper-soft px-2 py-1 text-xs font-semibold text-paper" title="Saarthi cannot place real orders. There is no broker connection.">
              <span className="h-1.5 w-1.5 rounded-full bg-paper" /> {tr("PAPER MODE · no real orders")}
            </span>
            <nav className="flex flex-wrap gap-0.5" aria-label="Sections">
              {TABS.map((tab) => (
                <button key={tab.id} disabled={tab.phase !== null} aria-current={tab.id === page ? "page" : undefined}
                  title={tab.phase ? `Arrives in Phase ${tab.phase}` : undefined} onClick={() => go(tab.id)}
                  className={`rounded-md px-2.5 py-1 text-sm ${tab.id === page ? "bg-panel-2 font-semibold" : tab.phase ? "text-faint disabled:cursor-not-allowed" : "text-muted hover:text-text"}`}>
                  {tr(tab.label)}
                </button>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-1 rounded-lg bg-panel-2 p-0.5 text-xs" role="radiogroup" aria-label="Detail level">
              {[false, true].map((v) => (
                <button key={String(v)} role="radio" aria-checked={pro === v} onClick={() => setPro(v)}
                  title={v ? "Show raw tool output, plan variants and score maths" : "Hide technical detail"}
                  className={`rounded-md px-2 py-1 font-medium ${pro === v ? "bg-panel shadow-sm" : "text-muted"}`}>{tr(v ? "Pro" : "Simple")}</button>
              ))}
            </div>
            <button onClick={() => setLang(lang === "en" ? "hi" : "en")} aria-label={lang === "en" ? "Switch labels to Hindi" : "Switch labels to English"}
              className="rounded-lg bg-panel-2 px-2 py-1.5 text-xs font-medium">{lang === "en" ? "हिं" : "EN"}</button>
            <div className="flex items-center gap-1 rounded-lg bg-panel-2 p-0.5 text-xs" role="radiogroup" aria-label="Data mode">
              {(["demo", "live"] as Mode[]).map((m) => (
                <button key={m} role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
                  className={`rounded-md px-2.5 py-1 font-medium ${mode === m ? "bg-panel shadow-sm" : "text-muted"}`}>
                  {tr(m === "demo" ? "Demo data" : "Live data")}
                </button>
              ))}
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1400px] space-y-4 px-4 py-5 md:px-6">
          {page === "ideas" && (route[0] === "idea" || route[0] === "swing") === false && (
            <div className="flex gap-1" role="tablist" aria-label="Idea type">
              {[["ideas", "Intraday · opening-range"], ["ideas/swing", "Swing · multi-day"]].map(([path, label]) => (
                <button key={path} role="tab" aria-selected={(route[1] === "swing") === (path === "ideas/swing")} onClick={() => go(path)}
                  className={`rounded-md px-3 py-1.5 text-sm ${(route[1] === "swing") === (path === "ideas/swing") ? "bg-panel font-semibold shadow-sm ring-1 ring-line" : "text-muted"}`}>{label}</button>
              ))}
            </div>
          )}
          {page === "ideas" && (route[0] === "idea" && route[1]
            ? <IdeaDetail id={route[1]} onBack={() => go("ideas")} onTrade={() => go(`desk/${route[1]}`)} />
            : route[0] === "swing" && route[1]
              ? <SwingDetail id={route[1]} mode={mode} onBack={() => go("ideas/swing")} onDesk={() => go("desk")} />
              : route[1] === "swing"
                ? <SwingList mode={mode} open={(id) => go(`swing/${id}`)} />
                : <IdeasPage mode={mode} open={(id) => go(`idea/${id}`)} />)}
          {page === "history" && <HistoryPage mode={mode} openIdea={(id) => go(`idea/${id}`)} />}
          {page === "performance" && <PerformancePage mode={mode} />}
          {page === "learn" && <LearnPage mode={mode} go={go} openTour={() => setTour(true)} />}
          {page === "replay" && <ReplayPage mode={mode} rid={route[1] ?? null} go={go} />}
          {page === "desk" && <PaperDesk mode={mode} ideaId={route[1] ?? null} clearIdea={() => go("desk")} />}
          {page === "today" && <>
          {/* ------------------------------------------------------------ session + jobs */}
          <section className="rounded-xl border border-line bg-panel px-4 py-3">
            <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
              <div className="min-w-[280px] flex-1">
                {t ? <SessionRibbon clock={t.clock} demo={mode === "demo"} /> : <Skeleton h={44} />}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <JobButton label="Evening scan" job={t?.jobs.evening_scan ?? null} busy={job.isPending && job.variables === "evening_scan"}
                  onRun={() => job.mutate("evening_scan")} disabled={job.isPending} />
                <JobButton label="Pre-market brief" job={t?.jobs.premarket_brief ?? null} busy={job.isPending && job.variables === "premarket_brief"}
                  onRun={() => job.mutate("premarket_brief")} disabled={job.isPending} />
              </div>
            </div>
            {mode === "demo" && (
              <p className="mt-2.5 text-xs text-muted">
                <b className="text-text">Demo data:</b> the real tools running on each repository's own archived NSE data, frozen at the
                pre-market of Mon 9 Nov 2026. Switch to <button onClick={() => setMode("live")} className="text-accent hover:underline">Live data</button> to scan today's market.
              </p>
            )}
            {job.error && <p className="mt-2 text-xs text-stop">Job failed to start: {(job.error as Error).message}</p>}
          </section>

          {today.error && <p className="rounded-lg bg-stop-soft p-3 text-sm text-stop">Cannot reach the Saarthi API. Is it running on port 8000?</p>}

          {empty && (
            <section className="rounded-xl border border-dashed border-line bg-panel px-6 py-10 text-center">
              <p className="text-base font-semibold">No briefing yet for {mode === "demo" ? "the demo session" : "this session"}</p>
              <p className="mx-auto mt-1 max-w-lg text-sm text-muted">
                Run the evening scan to build the watchlist from the exchange's end-of-day data, then the pre-market brief for market mood,
                events, sectors and filings.{mode === "live" && " Live runs fetch from NSE and Yahoo and can take a minute."}
              </p>
              <button onClick={async () => { await job.mutateAsync("evening_scan"); await job.mutateAsync("premarket_brief"); }}
                disabled={job.isPending}
                className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
                {job.isPending ? "Running…" : "Run both now"}
              </button>
            </section>
          )}

          {/* ------------------------------------------------------------ warnings */}
          {t && t.warnings.length > 0 && (
            <details className="rounded-xl border border-caution/40 bg-caution-soft px-4 py-2.5 text-sm">
              <summary className="cursor-pointer font-medium text-caution">
                {t.warnings.length} data note{t.warnings.length > 1 ? "s" : ""} from the tools
              </summary>
              <ul className="mt-2 space-y-1 text-xs text-muted">
                {t.warnings.map((w, i) => <li key={i}><b className="text-text">{w.step}:</b> {w.text}</li>)}
              </ul>
            </details>
          )}

          {/* ------------------------------------------------------------ grid */}
          {today.isLoading && (
            <div className="grid gap-4 lg:grid-cols-3"><Skeleton h={360} /><Skeleton h={360} /><Skeleton h={360} /></div>
          )}
          {t && !empty && (
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_340px]">
              <MoodCard mood={t.mood} />
              <EventsCard events={t.events} />
              <div className="space-y-4 lg:col-span-2 xl:col-span-1">
                <SectorsBreadth sectors={t.sectors} breadth={t.breadth} />
              </div>
              <div className="lg:col-span-2 xl:col-span-2"><Watchlist wl={t.watchlist} /></div>
              <div className="space-y-4 lg:col-span-2 xl:col-span-1">
                <DealsCard wl={t.watchlist} />
                <NewsCard news={t.news} />
              </div>
            </div>
          )}
          </>}
        </main>

        <footer className="mx-auto max-w-[1400px] px-4 pb-8 text-[11px] leading-relaxed text-faint md:px-6">
          Educational software for simulated trading only. Not investment advice; most intraday traders lose money. Trading logic by{" "}
          <a className="hover:underline" href="https://github.com/ogmanojdev/nse-trader-skill" target="_blank" rel="noreferrer">nse-trader-skill</a> (ogmanojdev) and{" "}
          <a className="hover:underline" href="https://github.com/Shubhamkumartrichy/claude-trading-skills-india" target="_blank" rel="noreferrer">claude-trading-skills-india</a> (Shubhamkumartrichy), MIT, unmodified
          {health.data && <> · pinned {health.data.repos.nse?.sha.slice(0, 7)} / {health.data.repos.india?.sha.slice(0, 7)} · {health.data.tools} tools</>}.
        </footer>
      </div>
      <EvidenceDrawer target={evidence} onClose={closeEvidence} />
      <Onboarding forceOpen={tour} onClose={() => setTour(false)} />
    </EvidenceCtx.Provider>
  );
}

function JobButton({ label, job, busy, onRun, disabled }: {
  label: string; job: JobView | null; busy: boolean; onRun: () => void; disabled: boolean;
}) {
  const tone = job?.status === "ok" ? "go" : job?.status === "partial" ? "caution" : job ? "stop" : "neutral";
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5">
      <div className="text-xs leading-tight">
        <p className="font-medium">{label}</p>
        <p className="text-faint num">
          {job ? <>for {job.session_day} · ran {job.started_at.slice(5, 16)} IST · {(job.duration_ms / 1000).toFixed(1)}s</> : "not run yet"}
        </p>
      </div>
      {job && <Pill tone={tone}>{job.status}</Pill>}
      <button onClick={onRun} disabled={disabled}
        className="rounded-md bg-panel-2 px-2 py-1 text-xs font-medium hover:bg-accent-soft hover:text-accent disabled:opacity-50"
        aria-label={`Run ${label} now`}>
        {busy ? "Running…" : "Run"}
      </button>
    </div>
  );
}
