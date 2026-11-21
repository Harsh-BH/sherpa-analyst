"use client";

import { useState } from "react";
import { Split } from "lucide-react";

import { VegaChart } from "@/components/charts/vega-chart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { View } from "@/lib/api";
import { useSherpa } from "@/lib/store";

const box = "grid min-w-0 gap-3 rounded-xl border bg-card p-3.5 shadow-sm";
const note = "text-xs text-muted-foreground wrap-anywhere";
const link =
  "rounded-[4px] px-1 py-0.5 font-medium text-foreground underline decoration-border underline-offset-2 hover:decoration-accent-blue focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none";

type Row = { _ask?: string; _segment?: string };

/** The waterfall's drillable segments (Python put `_ask` and `_segment` on their bars), once each. */
function drills(spec: View["key_charts"][number]["spec"]): { segment: string; ask: string }[] {
  const rows = ((spec.data as { values?: Row[] } | undefined)?.values ?? []).filter((r) => r._ask && r._segment);
  return [...new Map(rows.map((r) => [r._ask!, { segment: r._segment!, ask: r._ask! }])).values()];
}

/** The chart beside the claims: the mix/rate waterfall with its "Decompose by" picker, else the reconciliation
 * bridge, else the first evidence chart. Mount it with `key={run_id}` so a new answer starts on its default.
 * A waterfall segment asks why it moved, from its bar or (keyboard too) its button below. Each chart saves as
 * `<name>-<chart>.png`. */
export function KeyChart({ view, name }: { view: View; name: string }) {
  const { ask } = useSherpa();
  const charts = view.key_charts;
  const [dimension, setDimension] = useState(view.default_dimension ?? charts[0]?.dimension);
  const k = charts.find((c) => c.dimension === dimension) ?? charts[0];
  const drill = (d: Record<string, unknown>) => typeof d._ask === "string" && void ask(d._ask);
  const segments = k ? drills(k.spec) : [];

  if (k)
    return (
      <section data-testid="key-chart" className={box}>
        <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          Decompose by
          <Select value={k.dimension} onValueChange={setDimension}>
            <SelectTrigger size="sm" data-testid="decompose" className="text-foreground">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              {charts.map((c) => (
                <SelectItem key={c.dimension} value={c.dimension}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <VegaChart spec={k.spec} onDatumClick={drill} downloadName={`${name}-${k.dimension}`} />
        {segments.length > 0 && (
          <div data-testid="drill" className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-muted-foreground">
            <span className="mr-0.5">Ask why a segment moved, or click its bar:</span>
            {segments.map((d) => (
              <button key={d.ask} type="button" title={d.ask} className={link} onClick={() => void ask(d.ask)}>
                {d.segment}
              </button>
            ))}
          </div>
        )}
        {k.simpson ? (
          <p data-testid="simpson" className="flex items-start gap-2.5 rounded-md bg-muted px-3.5 py-2.5 text-[13.5px]">
            <Split className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 wrap-anywhere">{k.simpson}</span>
          </p>
        ) : (
          <p data-testid="key-summary" className={note}>
            {k.summary}
          </p>
        )}
        {view.drivers?.notes.map((n, i) => (
          <p key={i} className={note}>
            {n}
          </p>
        ))}
      </section>
    );

  if (view.recon)
    return (
      <section data-testid="key-chart" className={box}>
        <VegaChart spec={view.recon.spec} downloadName={`${name}-reconciliation`} />
      </section>
    );

  const fallback = view.fallback_chart;
  const chart = fallback && view.evidence.find((e) => e.id === fallback.value)?.chart;
  if (!chart) return null;
  return (
    <section data-testid="key-chart" className={box}>
      <VegaChart spec={chart} downloadName={`${name}-${fallback.value}`} />
      <p className={note}>{fallback.label}</p>
    </section>
  );
}
