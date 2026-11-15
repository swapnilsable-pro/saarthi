import type { Today } from "../api";
import { inr } from "../api";
import { Card, EvidenceLink, Pill, Term } from "../ui";

const QUAD_TONE = { Leading: "go", Improving: "accent", Weakening: "caution", Lagging: "stop" } as const;

export function SectorsBreadth({ sectors, breadth }: { sectors: Today["sectors"]; breadth: Today["breadth"] }) {
  return (
    <Card title="Sectors and breadth">
      {sectors ? (
        <div>
          <div className="flex items-center justify-between">
            <p className="text-sm"><span className="font-semibold">{sectors.tilt}</span>{sectors.size_read && <span className="text-muted"> · {sectors.size_read}</span>}</p>
            <EvidenceLink runId={sectors.run_id} label="Sector rotation (sector-rotation/sectors.py)" />
          </div>
          <ul className="mt-2 space-y-1">
            {sectors.leaders.map((s) => (
              <li key={s.label} className="flex items-center justify-between text-sm">
                <span>{s.label.replace(/^NIFTY /, "")}</span>
                <Pill tone={QUAD_TONE[s.quadrant as keyof typeof QUAD_TONE] ?? "neutral"}>{s.quadrant}</Pill>
              </li>
            ))}
          </ul>
        </div>
      ) : <p className="text-sm text-muted">Sector rotation unavailable.</p>}

      <div className="mt-4 border-t border-line pt-3">
        {breadth ? (
          <>
            <div className="flex items-center justify-between">
              <p className="text-sm"><Term k="breadth">Breadth</Term> <span className="font-semibold num">{breadth.score?.toFixed(0)}/100</span> <span className="text-muted">· {breadth.label}</span></p>
              <EvidenceLink runId={breadth.run_id} label="Market breadth (market-breadth/breadth.py)" />
            </div>
            {breadth.advances != null && (
              <div className="mt-2">
                <div className="flex h-2 overflow-hidden rounded-full" role="img" aria-label={`${breadth.advances} advances, ${breadth.declines} declines`}>
                  <div className="bg-go" style={{ flex: breadth.advances }} />
                  <div className="bg-stop" style={{ flex: breadth.declines }} />
                </div>
                <p className="mt-1 flex justify-between text-xs text-muted num"><span>{inr.format(breadth.advances)} up</span><span>{inr.format(breadth.declines)} down</span></p>
              </div>
            )}
            {breadth.read && <p className="mt-2 text-xs text-muted">{breadth.read}</p>}
          </>
        ) : <p className="text-sm text-muted">Breadth needs NSE's daily advance/decline CSV. Upload it to <code className="font-mono text-xs">data/uploads/breadth_ad.csv</code>.</p>}
      </div>
    </Card>
  );
}

export function DealsCard({ wl }: { wl: Today["watchlist"] }) {
  return (
    <Card title="Bulk & block deals" right={<EvidenceLink runId={wl.deals_run_id} label="Deals (nse-deals/deals.py)" />}>
      {wl.top_deals.length ? (
        <ul className="divide-y divide-line text-sm">
          {wl.top_deals.slice(0, 6).map((d) => (
            <li key={d.symbol + d.client} className="flex items-start justify-between gap-3 py-1.5">
              <div className="min-w-0">
                <p className="font-medium">{d.symbol}</p>
                <p className="truncate text-xs text-muted">{d.client}</p>
              </div>
              <span className={`shrink-0 num ${d.net_value_lacs >= 0 ? "text-go" : "text-stop"}`}>
                {d.net_value_lacs >= 0 ? "+" : "−"}₹{inr.format(Math.abs(d.net_value_lacs) / 100)}cr
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">No deals in the latest file.</p>}
    </Card>
  );
}

export function NewsCard({ news }: { news: Today["news"] }) {
  return (
    <Card title={<>Exchange filings <span className="font-normal normal-case text-faint">· {news.count}</span></>}
      right={<EvidenceLink runId={news.run_id} label="NSE announcements (nse-news/news.py)" />}>
      {news.items.length ? (
        <ul className="divide-y divide-line">
          {news.items.slice(0, 7).map((n) => (
            <li key={n.time + n.symbol} className="py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{n.symbol}</span>
                <span className="text-[11px] text-faint num">{n.time.replace("T", " ").slice(5, 16)}</span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted">{n.category}: {n.text}</p>
              {n.tags?.length > 0 && <div className="mt-1 flex gap-1">{n.tags.map((t) => <Pill key={t}>{t}</Pill>)}</div>}
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">No filings in the window.</p>}
    </Card>
  );
}
