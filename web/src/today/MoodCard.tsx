import { useState } from "react";
import type { Mood } from "../api";
import { inr } from "../api";
import { Card, EvidenceLink, Pill, Term } from "../ui";

const LEVEL = {
  go: { label: "Go", tone: "go", dot: "bg-go", soft: "bg-go-soft" },
  caution: { label: "Caution", tone: "caution", dot: "bg-caution", soft: "bg-caution-soft" },
  stand_aside: { label: "Stand aside", tone: "stop", dot: "bg-stop", soft: "bg-stop-soft" },
  unknown: { label: "Unknown", tone: "neutral", dot: "bg-faint", soft: "bg-panel-2" },
} as const;

const EFFECT: Record<string, { text: string; cls: string }> = {
  base: { text: "sets base", cls: "text-muted" },
  down: { text: "▼ steps down", cls: "text-caution" },
  none: { text: "no change", cls: "text-faint" },
  info: { text: "context", cls: "text-faint" },
};

export function MoodCard({ mood }: { mood: Mood }) {
  const [showRule, setShowRule] = useState(false);
  const lv = LEVEL[mood.level];
  const r = mood.regime;
  const pct = (v?: number) => (v === undefined || v === null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);

  return (
    <Card title="Market mood" right={<EvidenceLink runId={mood.factors[0]?.run_id} label="Market regime (market-regime/regime.py)" />}>
      <div className={`flex items-start gap-3 rounded-lg p-3 ${lv.soft}`}>
        <span className={`mt-1.5 inline-block h-3 w-3 shrink-0 rounded-full ${lv.dot}`} aria-hidden />
        <div>
          <p className="text-lg leading-tight font-semibold">{lv.label}</p>
          <p className="mt-0.5 text-sm text-muted">{mood.headline}</p>
        </div>
      </div>

      {r && (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
          <div><dt className="text-xs text-faint">{r.index}</dt><dd className="font-semibold num">{inr.format(r.close)}</dd></div>
          <div><dt className="text-xs text-faint">Regime</dt><dd className="font-medium">{r.label}</dd></div>
          <div><dt className="text-xs text-faint"><Term k="exposure">Exposure ceiling</Term></dt><dd className="font-medium num">{r.exposure_ceiling_pct}% · max {r.max_new_positions} new</dd></div>
          <div><dt className="text-xs text-faint"><Term k="distribution">Distribution days</Term> (25)</dt><dd className="font-medium num">{r.distribution_days_25 ?? "–"}</dd></div>
          <div><dt className="text-xs text-faint">vs 50-day / 200-day avg</dt><dd className="font-medium num">{pct(r.vs_sma50_pct)} / {pct(r.vs_sma200_pct)}</dd></div>
          <div><dt className="text-xs text-faint">From 52-week high</dt><dd className="font-medium num">{pct(r.drawdown_pct)}</dd></div>
        </dl>
      )}

      <div className="mt-4">
        <p className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">How the mood was reached</p>
        <ul className="divide-y divide-line rounded-lg border border-line text-sm">
          {mood.factors.map((f) => (
            <li key={f.label} className="flex items-start justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="font-medium">{f.label}: <span className="font-normal">{f.value}</span></p>
                {f.detail && <p className="mt-0.5 text-xs text-muted">{f.detail}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className={`text-xs ${EFFECT[f.effect].cls}`}>{EFFECT[f.effect].text}</span>
                <EvidenceLink runId={f.run_id} label={f.label} />
              </div>
            </li>
          ))}
        </ul>
        <button onClick={() => setShowRule((v) => !v)} className="mt-2 text-xs text-accent hover:underline" aria-expanded={showRule}>
          {showRule ? "Hide the rule" : "Show the exact rule"}
        </button>
        {showRule && <p className="mt-1.5 rounded-lg bg-panel-2 p-2.5 text-xs leading-relaxed text-muted">{mood.rule}</p>}
      </div>

      {r && r.what_would_change.length > 0 && (
        <div className="mt-4">
          <p className="mb-1 text-xs font-medium tracking-wide text-faint uppercase">What would change it</p>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">
            {r.what_would_change.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </div>
      )}
      {r && <p className="mt-3 text-[11px] text-faint">Index data as of {r.as_of}. <Pill tone="neutral">regime tool</Pill></p>}
    </Card>
  );
}
