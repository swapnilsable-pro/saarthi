import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "./api";
import { Pill } from "./ui";
import { usePrefs } from "./prefs";

export function EvidenceDrawer({ target, onClose }: { target: { runId: string; label: string } | null; onClose: () => void }) {
  const run = useQuery({ queryKey: ["run", target?.runId], queryFn: () => api.run(target!.runId), enabled: !!target });
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools, staleTime: Infinity });
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!target) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  const { pro } = usePrefs();
  if (!target) return null;
  const r = run.data;
  const tool = tools.data?.find((t) => t.id === r?.tool_id);
  const repoName = r?.repo === "nse" ? "ogmanojdev/nse-trader-skill" : "Shubhamkumartrichy/claude-trading-skills-india";
  const json = r?.output_json !== undefined ? JSON.stringify(r.output_json, null, 2) : "";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={`Evidence: ${target.label}`}>
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[640px] flex-col border-l border-line bg-panel shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <p className="text-xs font-medium tracking-wide text-faint uppercase">Evidence</p>
            <h3 className="mt-0.5 text-base font-semibold">{target.label}</h3>
            {tool && <p className="mt-1 text-sm text-muted">{tool.role}</p>}
          </div>
          <button ref={closeRef} onClick={onClose} className="rounded-md px-2 py-1 text-muted hover:bg-panel-2" aria-label="Close evidence">✕</button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {run.isLoading && <p className="text-muted">Loading run…</p>}
          {run.error && <p className="text-stop">Could not load this run.</p>}
          {r && (
            <>
              <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">Tool</dt>
                <dd className="font-mono text-[13px]">{r.tool_id}</dd>
                <dt className="text-muted">Status</dt>
                <dd><Pill tone={r.status === "ok" ? "go" : "stop"}>{r.status}</Pill> <span className="ml-2 text-muted num">exit {r.exit_code} · {r.duration_ms} ms</span></dd>
                <dt className="text-muted">Repository</dt>
                <dd>
                  <a className="text-accent hover:underline" href={`https://github.com/${repoName}/tree/${r.repo_sha}`} target="_blank" rel="noreferrer">{repoName}</a>
                  <span className="ml-2 font-mono text-xs text-faint">@{r.repo_sha.slice(0, 10)}</span>
                </dd>
                <dt className="text-muted">Ran as of</dt>
                <dd className="num">{r.as_of ? `${r.as_of} IST (point-in-time)` : "the moment it ran (live)"}</dd>
                <dt className="text-muted">Recorded</dt>
                <dd className="num">{r.created_at.replace("T", " ").slice(0, 19)} UTC</dd>
              </dl>

              <details open={pro}>
                <summary className="mb-1.5 cursor-pointer text-xs font-medium tracking-wide text-faint uppercase">Exact command</summary>
                <pre className="overflow-x-auto rounded-lg bg-panel-2 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap break-all">{r.argv.join(" ")}</pre>
              </details>

              {Object.keys(r.input_hashes).length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">Input fingerprints (sha256)</p>
                  <ul className="space-y-1 font-mono text-[11px] text-muted">
                    {Object.entries(r.input_hashes).map(([k, v]) => (
                      <li key={k} className="break-all"><span className="text-text">{k}</span> {v.slice(0, 16)}…</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <p className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">Tool output (JSON, as printed)</p>
                <pre className="max-h-[52vh] overflow-auto rounded-lg bg-panel-2 p-3 font-mono text-[11.5px] leading-relaxed">
                  {json || r.output_text}
                </pre>
              </div>

              {r.stderr?.trim() && (
                <details>
                  <summary className="cursor-pointer text-xs font-medium tracking-wide text-faint uppercase">stderr</summary>
                  <pre className="mt-2 overflow-x-auto rounded-lg bg-panel-2 p-3 font-mono text-[11px] text-muted">{r.stderr}</pre>
                </details>
              )}
            </>
          )}
        </div>
        <footer className="border-t border-line px-5 py-3 text-xs text-faint">
          Saarthi computed none of this. It is the unmodified tool's own output, stored in the append-only ledger.
        </footer>
      </aside>
    </div>
  );
}
