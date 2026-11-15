import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Card } from "../ui";

/** Optional Claude explanation of an idea's recorded evidence. Hidden unless the API was started
 *  with SAARTHI_NARRATOR=1. The template text above it never depends on this. */
export function Narrator({ id }: { id: string }) {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 300_000 });
  const run = useMutation({
    mutationFn: async () => {
      const r = await fetch(`/api/ideas/${id}/narrate`, { method: "POST" });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);
      return body as { text: string; model: string };
    },
  });
  if (!(health.data as { narrator?: boolean } | undefined)?.narrator) return null;
  return (
    <Card title="Explain with Claude" right={<span className="text-[11px] text-faint">optional · uses your Anthropic account</span>}>
      {run.data ? (
        <>
          <p className="whitespace-pre-line text-sm leading-relaxed">{run.data.text}</p>
          <p className="mt-2 text-[11px] text-faint">Written by {run.data.model} from the evidence on this page only. It decides nothing; the verdict above comes from the rule.</p>
        </>
      ) : (
        <button onClick={() => run.mutate()} disabled={run.isPending} className="rounded-lg border border-line px-3 py-2 text-sm hover:border-accent disabled:opacity-50">
          {run.isPending ? "Asking Claude…" : "Explain this idea in plain English"}
        </button>
      )}
      {run.error && <p className="mt-2 text-sm text-stop">{(run.error as Error).message}</p>}
    </Card>
  );
}
