"use client";

import { useState } from "react";
import { Split } from "lucide-react";

import { VegaChart } from "@/components/charts/vega-chart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { View } from "@/lib/api";

const box = "grid min-w-0 gap-3 rounded-xl border bg-card p-3.5 shadow-sm";
const note = "text-xs text-muted-foreground wrap-anywhere";

/** The chart beside the claims: the mix/rate waterfall with its "Decompose by" picker, else the reconciliation
 * bridge, else the first evidence chart. Mount it with `key={run_id}` so a new answer starts on its default. */
export function KeyChart({ view }: { view: View }) {
  const charts = view.key_charts;
  const [dimension, setDimension] = useState(view.default_dimension ?? charts[0]?.dimension);
  const k = charts.find((c) => c.dimension === dimension) ?? charts[0];

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
        <VegaChart spec={k.spec} />
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
        <VegaChart spec={view.recon.spec} />
      </section>
    );

  const fallback = view.fallback_chart;
  const chart = fallback && view.evidence.find((e) => e.id === fallback.value)?.chart;
  if (!chart) return null;
  return (
    <section data-testid="key-chart" className={box}>
      <VegaChart spec={chart} />
      <p className={note}>{fallback.label}</p>
    </section>
  );
}
