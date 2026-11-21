"use client";

import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";
import type { View } from "@/lib/api";
import { useSherpa } from "@/lib/store";

type Kind = View["claims"][number]["kind"];

// The tag text carries the kind; the mark's shape is a second cue. All grey: the hue rule keeps hue for DQ and confidence.
const KINDS: Record<Kind, { tag: string; mark: string }> = {
  fact: { tag: "Fact", mark: "rounded-[2px] bg-foreground" },
  hypothesis: { tag: "Hypothesis", mark: "rounded-[2px] border-[1.5px] border-dashed border-foreground" },
  recommendation: { tag: "Recommendation", mark: "rounded-full border-[1.5px] border-foreground" },
  caveat: { tag: "Caveat", mark: "rotate-45 bg-foreground" },
};

/** An evidence id that selects that entry in the rail (and opens the rail sheet on narrow screens). */
export function EvidenceChip({ id, missing }: { id: string; missing?: boolean }) {
  const { selectedEvidenceId, selectEvidence, setRailOpen } = useSherpa();
  if (missing)
    return (
      <span className="font-mono text-[11.5px] text-muted-foreground">
        {id} · not in this bundle
      </span>
    );
  return (
    <button
      type="button"
      data-testid={`chip-${id}`}
      aria-label={`Evidence ${id}`}
      aria-pressed={selectedEvidenceId === id}
      onClick={() => {
        selectEvidence(id);
        setRailOpen(true);
      }}
      className="rounded-[4px] border border-input bg-card px-1.5 py-1 font-mono text-[11.5px] leading-none transition-[color,background-color,border-color,scale] duration-150 ease-out active:scale-[0.98] aria-[pressed=false]:hover:border-accent-blue aria-[pressed=false]:hover:text-accent-blue focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none aria-pressed:border-accent-blue aria-pressed:bg-accent-blue aria-pressed:text-card"
    >
      {id}
    </button>
  );
}

/** The claims in bundle order; those citing the selected evidence are highlighted. */
export function Claims({ claims }: { claims: View["claims"] }) {
  const { selectedEvidenceId } = useSherpa();
  if (!claims.length) return null;
  return (
    // data-swap-in: when a result replaces its partial, the claims rise in (the rest of the answer was drawn already)
    <section data-swap-in className="grid gap-2">
      <h3 className="section-label">What the evidence says</h3>
      <ol className="overflow-hidden rounded-xl border bg-card shadow-sm">
        {claims.map((c, j) => {
          const k = KINDS[c.kind];
          return (
            <li
              key={c.n}
              data-testid="claim"
              data-kind={c.kind}
              data-cites={c.evidence_ids.join(" ")}
              data-highlight={selectedEvidenceId !== null && c.evidence_ids.includes(selectedEvidenceId)}
              // rises after its section (whose --i it inherits), one step per claim
              style={{ "--j": j } as CSSProperties}
              className="rise grid gap-x-3 gap-y-1 border-b px-3 py-2.5 transition-[background-color,box-shadow] duration-200 ease-out last:border-b-0 data-[highlight=true]:bg-accent-blue/8 data-[highlight=true]:shadow-[inset_2px_0_0_var(--accent-blue)] sm:grid-cols-[124px_minmax(0,1fr)]"
            >
              <span className="mt-0.5 inline-flex items-center gap-2 self-start text-[11.5px] font-medium text-muted-foreground">
                <span className="w-3 font-mono">{c.n}</span>
                <i aria-hidden className={cn("size-2 shrink-0", k.mark)} />
                <span>{k.tag}</span>
              </span>
              <div className="grid min-w-0 gap-1.5">
                <p className="text-sm wrap-anywhere">{c.text}</p>
                {!c.ok && (
                  <p className="text-xs text-muted-foreground wrap-anywhere">
                    Claim checker: {c.problems.join("; ") || "failed"}
                  </p>
                )}
                {c.evidence_ids.length + c.missing_ids.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {c.evidence_ids.map((id) => (
                      <EvidenceChip key={id} id={id} />
                    ))}
                    {c.missing_ids.map((id) => (
                      <EvidenceChip key={id} id={id} missing />
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
