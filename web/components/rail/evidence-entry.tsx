"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Copy } from "lucide-react";

import { DataTable, KVList } from "@/components/answer/data-table";
import { VegaChart } from "@/components/charts/vega-chart";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { View } from "@/lib/api";
import { useSherpa } from "@/lib/store";
import { cn } from "@/lib/utils";

type Evidence = View["evidence"][number];

const caption = "section-label";

/** Scroll the entry's nearest scrolling ancestor (the rail) to the entry's top, less its scroll margin (the
 * sticky tab bar). Nothing outside the rail moves. Smooth only when asked and motion is not reduced. */
function scrollRailTo(el: HTMLElement, smooth: boolean) {
  let box = el.parentElement;
  while (box && !/auto|scroll/.test(getComputedStyle(box).overflowY)) box = box.parentElement;
  if (!box) return;
  const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  box.scrollTo({
    top: box.scrollTop + el.getBoundingClientRect().top - box.getBoundingClientRect().top - margin,
    behavior: smooth && !reduce ? "smooth" : "auto",
  });
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const label = { idle: "Copy SQL", copied: "Copied", failed: "Copy failed" }[state];
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed"); // no clipboard permission, or not a secure context
    }
    setTimeout(() => setState("idle"), 1500);
  };
  return (
    <Button variant="ghost" size="xs" aria-label={label} title={label} onClick={copy}>
      {state === "copied" ? <Check /> : <Copy />}
      {state === "failed" && label}
    </Button>
  );
}

/** One evidence entry in the rail. Selected, it opens (height animation) to show what the claims citing it rest on.
 * Its chart saves as `<name>-<evidence id>.png`. */
export function EvidenceEntry({ e, name }: { e: Evidence; name: string }) {
  const { selectedEvidenceId, selectEvidence } = useSherpa();
  const selected = selectedEvidenceId === e.id;
  const ref = useRef<HTMLLIElement>(null);
  // Mounted already selected (the rail or its tab just opened): jump there. Selected while the rail shows: glide
  // there once the entry has opened (onAnimationEnd below), when the rail is tall enough to bring it to the top.
  const shown = useRef(false);
  useEffect(() => {
    if (selected && !shown.current) scrollRailTo(ref.current!, false);
    shown.current = true;
  }, [selected]);

  return (
    <Collapsible asChild open={selected} onOpenChange={(open) => selectEvidence(open ? e.id : null)}>
      {/* scroll-mt-10 clears the rail's sticky tab bar (h-10) */}
      <li ref={ref} data-testid={`evidence-${e.id}`} data-selected={selected} className="scroll-mt-10 border-b last:border-b-0">
        <CollapsibleTrigger className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition-colors duration-200 ease-out hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-inset aria-expanded:bg-accent-blue/8 aria-expanded:shadow-[inset_2px_0_0_var(--accent-blue)]">
          <span className="mt-px font-mono text-xs">{e.id}</span>
          <span className="grid min-w-0 flex-1 gap-0.5">
            <span className="text-[13px] leading-snug wrap-anywhere">{e.title}</span>
            <span className="text-xs text-muted-foreground">{e.kind.replaceAll("_", " ")}</span>
          </span>
          <ChevronRight
            className={cn("mt-px size-4 shrink-0 text-muted-foreground transition-transform duration-200 ease-out", selected && "rotate-90")}
          />
        </CollapsibleTrigger>
        {/* Switching to another entry closes this one at once, so the rail scrolls in a settled layout. */}
        <CollapsibleContent
          className={cn(selectedEvidenceId !== null && "data-[state=closed]:animate-none")}
          onAnimationEnd={(ev) => selected && ev.target === ev.currentTarget && scrollRailTo(ref.current!, true)}
        >
          <div className="grid min-w-0 gap-4 px-4 pt-3 pb-4">
            <KVList items={e.meta} />
            {e.sql.map((s, i) => (
              <section key={i} className="grid min-w-0 gap-1">
                <div className="flex items-center justify-between gap-2">
                  <h4 className={cn(caption, "min-w-0 wrap-anywhere")}>{s.label}</h4>
                  <CopyButton text={s.value} />
                </div>
                <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                  {s.value}
                </pre>
              </section>
            ))}
            {e.values.length > 0 && (
              <section className="grid min-w-0 gap-1">
                <h4 className={caption}>Values claims can cite</h4>
                <DataTable table={{ columns: ["placeholder", "value"], rows: e.values.map((kv) => [kv.label, kv.value]) }} />
              </section>
            )}
            {e.table && (
              <section className="grid min-w-0 gap-1">
                <h4 className={caption}>Result table</h4>
                <DataTable table={e.table} />
              </section>
            )}
            {e.chart && <VegaChart spec={e.chart} downloadName={`${name}-${e.id}`} />}
            <p className="text-xs text-muted-foreground">
              {e.cited_by.length ? `Cited by claim ${e.cited_by.join(", ")}` : "No claim cites this evidence."}
            </p>
          </div>
        </CollapsibleContent>
      </li>
    </Collapsible>
  );
}
