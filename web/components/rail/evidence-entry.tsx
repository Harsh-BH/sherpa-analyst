"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Copy } from "lucide-react";

import { DataTable, KVList } from "@/components/answer/data-table";
import { VegaChart } from "@/components/charts/vega-chart";
import { Button } from "@/components/ui/button";
import type { View } from "@/lib/api";
import { useSherpa } from "@/lib/store";
import { cn } from "@/lib/utils";

type Evidence = View["evidence"][number];

const caption = "text-xs font-medium text-muted-foreground";

/** Scroll the entry's nearest scrolling ancestor (the rail) to the entry's top, less its scroll margin (the
 * sticky tab bar). Nothing outside the rail moves. */
function scrollRailTo(el: HTMLElement) {
  let box = el.parentElement;
  while (box && !/auto|scroll/.test(getComputedStyle(box).overflowY)) box = box.parentElement;
  const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
  if (box) box.scrollTop += el.getBoundingClientRect().top - box.getBoundingClientRect().top - margin;
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

/** One evidence entry in the rail. Selected, it opens to show what the claims citing it rest on. */
export function EvidenceEntry({ e }: { e: Evidence }) {
  const { selectedEvidenceId, selectEvidence } = useSherpa();
  const selected = selectedEvidenceId === e.id;
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) scrollRailTo(ref.current!);
  }, [selected]);

  return (
    // scroll-mt-10 clears the rail's sticky tab bar (h-10)
    <li ref={ref} data-testid={`evidence-${e.id}`} data-selected={selected} className="scroll-mt-10 border-b last:border-b-0">
      <button
        type="button"
        aria-expanded={selected}
        onClick={() => selectEvidence(selected ? null : e.id)}
        className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none aria-expanded:bg-muted/60"
      >
        <span className="mt-px font-mono text-xs">{e.id}</span>
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="text-[13px] leading-snug wrap-anywhere">{e.title}</span>
          <span className="text-xs text-muted-foreground">{e.kind.replaceAll("_", " ")}</span>
        </span>
        <ChevronRight
          className={cn("mt-px size-4 shrink-0 text-muted-foreground transition-transform", selected && "rotate-90")}
        />
      </button>
      {selected && (
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
          {e.chart && <VegaChart spec={e.chart} />}
          <p className="text-xs text-muted-foreground">
            {e.cited_by.length ? `Cited by claim ${e.cited_by.join(", ")}` : "No claim cites this evidence."}
          </p>
        </div>
      )}
    </li>
  );
}
