import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, ideasApi, type Mode } from "../api";
import { Card } from "../ui";

type Entry = { term: string; plain: string; more?: string; skill?: { repo: "nse" | "india"; path: string }; see?: string };

const GLOSSARY: Entry[] = [
  { term: "Opening range (ORB)", plain: "The highest and lowest price in the first 15 minutes (09:15 to 09:30). A close above its high is an opening-range breakout.", skill: { repo: "nse", path: "nse-scanner/SKILL.md" }, see: "ideas" },
  { term: "R (risk unit)", plain: "The rupees you lose if the stop is hit. A +2R trade made twice what it risked; −1R lost exactly what was planned.", see: "performance" },
  { term: "Stop-loss", plain: "The price at which the trade is closed to cap the loss. Saarthi's simulator treats it as a market sell when price trades through it.", skill: { repo: "india", path: "skills/stop-loss-strategies/SKILL.md" } },
  { term: "Net of costs", plain: "After STT, stamp duty, exchange and SEBI fees, brokerage and GST. A trade that wins 1R before costs can lose money after them.", skill: { repo: "india", path: "skills/trading-costs/SKILL.md" } },
  { term: "STT", plain: "Securities Transaction Tax, charged by the government on the sell side of an intraday trade (both sides for delivery)." },
  { term: "MIS / square-off", plain: "MIS is an intraday product. Brokers close open MIS positions themselves near 15:20; Saarthi exits at 15:15 to stay ahead of that." },
  { term: "CNC / delivery", plain: "Buying shares to hold overnight or longer. Pays STT on both sides and a DP charge on each sell." },
  { term: "GTT", plain: "Good-Till-Triggered: an order that waits (for weeks) until price reaches a trigger, then sends a limit order. Swing ideas use one to buy above a pivot.", skill: { repo: "india", path: "skills/breakout-planner/SKILL.md" }, see: "swing" },
  { term: "Chase limit", plain: "The highest price a breakout buy may pay. If the stock gaps above it, the order goes unfilled on purpose." },
  { term: "Price band / circuit", plain: "The exchange's daily limit on how far a stock may move. A stop beyond the band cannot fill." },
  { term: "ASM / GSM", plain: "NSE's surveillance lists. Stocks on them need full upfront margin and often cannot be traded intraday." },
  { term: "Delivery %", plain: "How much of the day's traded quantity was actually taken into demat accounts. High delivery suggests real buying rather than churn." },
  { term: "Bulk / block deal", plain: "Large trades the exchange publishes daily, with the buyer's or seller's name.", skill: { repo: "nse", path: "nse-deals/SKILL.md" } },
  { term: "Market regime", plain: "Whether the index is in a confirmed uptrend, under pressure, attempting a rally, or in correction. It sets Saarthi's market mood.", skill: { repo: "india", path: "skills/market-regime/SKILL.md" }, see: "today" },
  { term: "Breadth", plain: "How many stocks are rising with the index. A rally carried by a few stocks is fragile.", skill: { repo: "india", path: "skills/market-breadth/SKILL.md" } },
  { term: "Time Machine", plain: "nse-trader-skill's simulator: it replays the rest of the session 10,000 times from the stock's own past 5-minute bars, and every past day the same rule fired, and reports the odds after costs.", skill: { repo: "nse", path: "nse-timemachine/SKILL.md" }, see: "ideas" },
  { term: "Expectancy", plain: "The average result per trade if you took it many times, after costs. Positive expectancy is the bar for TAKE." },
  { term: "Calibration", plain: "Whether predicted odds match what actually happened. If the Time Machine says 40%, about 40% of those targets should be hit.", see: "performance" },
  { term: "Ghost trade", plain: "An idea traded exactly as planned after the session, in a separate book, to judge the system. Ghosts are hindsight and never influence a decision.", see: "history" },
  { term: "Stage 2 / VCP", plain: "Stage 2: a stock in a rising trend above its moving averages. VCP: a base where each pullback is smaller than the last, before a breakout.", skill: { repo: "india", path: "skills/breakout-planner/SKILL.md" }, see: "swing" },
  { term: "Profit factor", plain: "Total rupees won divided by total rupees lost. Above 1 means the wins outweighed the losses." },
  { term: "MAE / MFE", plain: "Maximum adverse and favourable excursion: the worst and best the trade went while it was open, in R." },
];

export function LearnPage({ mode, go, openTour }: { mode: Mode; go: (p: string) => void; openTour: () => void }) {
  const [q, setQ] = useState("");
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 300_000 });
  const ideas = useQuery({ queryKey: ["ideas", mode], queryFn: () => ideasApi.list(mode) });
  const shown = useMemo(() => GLOSSARY.filter((g) => (g.term + g.plain).toLowerCase().includes(q.toLowerCase())), [q]);
  const sha = (r: "nse" | "india") => health.data?.repos[r]?.sha ?? "main";
  const repoUrl = (r: "nse" | "india") => r === "nse" ? "https://github.com/ogmanojdev/nse-trader-skill" : "https://github.com/Shubhamkumartrichy/claude-trading-skills-india";
  const latestIdea = ideas.data?.ideas[0]?.id;
  const seeIt = (k?: string) => {
    if (!k) return null;
    const map: Record<string, [string, string]> = {
      ideas: [latestIdea ? `idea/${latestIdea}` : "ideas", latestIdea ? "Open a real example" : "See Ideas"],
      swing: ["ideas/swing", "See swing ideas"], performance: ["performance", "See it on Performance"],
      history: ["history", "See it in History"], today: ["", "See it on Today"],
    };
    const [path, label] = map[k];
    return <button onClick={() => go(path || "today")} className="text-xs text-accent hover:underline">{label} →</button>;
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-2xl">
            <h1 className="text-lg font-semibold">Learn</h1>
            <p className="mt-1 text-sm text-muted">The ideas behind every screen, in plain words, with a link to the open-source skill that explains it in depth and an example from your own data.</p>
          </div>
          <button onClick={openTour} className="rounded-lg border border-line px-3 py-2 text-sm hover:border-accent">Take the tour again</button>
        </div>
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card title="Glossary" right={<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search terms" aria-label="Search glossary" className="h-7 w-44 rounded-md border border-line bg-panel px-2 text-xs" />}>
          <dl className="divide-y divide-line">
            {shown.map((g) => (
              <div key={g.term} className="py-3">
                <dt className="font-semibold">{g.term}</dt>
                <dd className="mt-1 text-sm text-muted">{g.plain}</dd>
                <dd className="mt-1.5 flex flex-wrap gap-4">
                  {g.skill && <a href={`${repoUrl(g.skill.repo)}/blob/${sha(g.skill.repo)}/${g.skill.path}`} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">
                    Read the skill: {g.skill.repo === "nse" ? "nse-trader-skill" : "claude-trading-skills-india"} ↗</a>}
                  {seeIt(g.see)}
                </dd>
              </div>
            ))}
            {!shown.length && <p className="py-4 text-sm text-muted">No term matches.</p>}
          </dl>
        </Card>
        <div className="space-y-4">
          <Card title="How Saarthi decides">
            <ol className="list-decimal space-y-2 pl-5 text-sm text-muted">
              <li><b className="text-text">Saarthi computes no prices or odds.</b> Every number comes from an unmodified tool in the two repositories, stored with the exact command and data so it can be re-run.</li>
              <li>Each idea passes a fixed list of checks (G0–G6 intraday, S0–S5 + B1 swing). The rule is printed on every idea.</li>
              <li>A failed check makes it <b className="text-stop">SKIP</b>; a missing piece of data caps it at <b className="text-caution">WATCH</b>; only an idea that passes everything is a <b className="text-go">TAKE</b>.</li>
              <li>Decisions are made with tools told it is that exact moment, so they never see later prices. After the session, every idea is traded as planned in a ghost book to check whether the checks help.</li>
            </ol>
          </Card>
          <Card title="What it is not">
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
              <li>Not investment advice. For advice on your situation, talk to a SEBI-registered investment adviser.</li>
              <li>Not connected to any broker. It cannot place, modify or cancel a real order.</li>
              <li>Not a promise: a positive backtest or good odds on a small sample can be luck. Look at the calibration page before trusting the odds.</li>
            </ul>
          </Card>
          <Card title="Credits">
            <p className="text-sm text-muted">Trading logic: <a className="text-accent hover:underline" href={repoUrl("nse")} target="_blank" rel="noreferrer">nse-trader-skill</a> (ogmanojdev) and <a className="text-accent hover:underline" href={repoUrl("india")} target="_blank" rel="noreferrer">claude-trading-skills-india</a> (Shubhamkumartrichy), both MIT, used unmodified at pinned commits {sha("nse").slice(0, 7)} / {sha("india").slice(0, 7)}.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
