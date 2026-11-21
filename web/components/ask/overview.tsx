"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";

import { ChartCard } from "@/components/charts/chart-card";
import { VegaChart } from "@/components/charts/vega-chart";
import { Skeleton } from "@/components/ui/skeleton";
import { getOverview, type Kpi, type OverviewResponse } from "@/lib/api";
import { useSherpa } from "@/lib/store";
import { cn } from "@/lib/utils";

const ARROWS = { up: ArrowUpRight, down: ArrowDownRight, flat: ArrowRight };
const TONES = { positive: "text-positive", negative: "text-negative", neutral: "text-muted-foreground" };

function KpiCard({ k, i }: { k: Kpi; i: number }) {
  const Arrow = ARROWS[k.direction];
  return (
    <div
      data-testid="kpi-card"
      data-tone={k.tone}
      style={{ "--i": i } as CSSProperties}
      className="rise flex min-w-0 flex-col rounded-xl border bg-card p-3.5 pb-2 shadow-sm"
    >
      <div className="section-label">{k.label}</div>
      <div data-testid="kpi-value" className="mt-auto pt-1.5 text-xl font-semibold tabular-nums">
        {k.value}
      </div>
      <div className={cn("flex items-center gap-1 text-xs font-medium tabular-nums", TONES[k.tone])}>
        <Arrow aria-hidden className="size-3.5" />
        <span data-testid="kpi-delta">{k.delta}</span>
      </div>
      <div className="text-xs text-muted-foreground">vs prev 30 days</div>
      {/* fixed height: the lazy chart's loading skeleton is taller than a sparkline */}
      <div role="img" aria-label={`${k.summary}; daily trend`} className="mt-1.5 h-11 overflow-hidden">
        <VegaChart spec={k.spark} />
      </div>
    </div>
  );
}

/** Home, on the empty Ask page: four KPIs for the last 30 days and the daily success rate, as the current
 * persona. Refetched when the persona changes; hidden when the API says it is unavailable or the call fails. */
export function Overview() {
  const { persona } = useSherpa();
  const [got, setGot] = useState<{ persona: string; data: OverviewResponse | null } | null>(null);

  useEffect(() => {
    if (!persona) return;
    const c = new AbortController();
    getOverview(persona, c.signal).then(
      (data) => setGot({ persona, data }),
      () => c.signal.aborted || setGot({ persona, data: null }), // a failed call hides the panel, like unavailable
    );
    return () => c.abort();
  }, [persona]);

  if (!persona) return null;
  const data = got?.persona === persona ? got.data : undefined;
  if (data === undefined)
    return (
      <div data-testid="overview-loading" aria-hidden className="grid gap-2.5">
        <Skeleton className="h-4 w-56" />
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[134px] rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[290px] rounded-xl" />
      </div>
    );
  if (!data?.available) return null;
  return (
    <section data-testid="overview" aria-labelledby="overview-title" className="grid gap-2.5">
      <h2 id="overview-title" className="text-[13px] text-muted-foreground">
        <span className="section-label">Overview</span> · Last 30 days · as of {data.as_of}
      </h2>
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        {data.kpis.map((k, i) => (
          <KpiCard key={k.key} k={k} i={i} />
        ))}
      </div>
      <ChartCard chart={data.trend} i={data.kpis.length} />
    </section>
  );
}
