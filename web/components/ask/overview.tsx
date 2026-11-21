"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";

import { ChartCard } from "@/components/charts/chart-card";
import { VegaChart } from "@/components/charts/vega-chart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { getOverview, type Kpi, type OverviewResponse } from "@/lib/api";
import { useSherpa } from "@/lib/store";
import { cn } from "@/lib/utils";

const ARROWS = { up: ArrowUpRight, down: ArrowDownRight, flat: ArrowRight };
const TONES = { positive: "text-positive", negative: "text-negative", neutral: "text-muted-foreground" };

/** Ask from a home panel (a trend day, a data-health row): back to the top of the centre, where the trace
 * shows, with the rail sheet closed below 1280 px. */
export function useAskFromHome() {
  const { ask, setRailOpen } = useSherpa();
  return useCallback(
    (question: string) => {
      document.querySelector('[data-testid="question"]')?.closest(".overflow-y-auto")?.scrollTo({ top: 0 });
      setRailOpen(false);
      void ask(question);
    },
    [ask, setRailOpen],
  );
}

function KpiCard({ k, i }: { k: Kpi; i: number }) {
  const Arrow = ARROWS[k.direction];
  return (
    <div
      data-testid="kpi-card"
      data-tone={k.tone}
      style={{ "--i": i } as CSSProperties}
      className="rise flex min-h-[172px] min-w-0 flex-col rounded-xl border bg-card p-3.5 pb-2 shadow-sm"
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
  const askWhy = useAskFromHome();
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
      // the loaded panel's measured heights (heading 20, KPI card min 172, trend card 334 px): nothing below jumps
      <div data-testid="overview-loading" aria-hidden className="@container grid gap-2.5">
        <Skeleton className="h-5 w-56" />
        <div className="grid grid-cols-2 gap-2.5 @2xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[172px] rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[334px] rounded-xl" />
      </div>
    );
  if (!data?.available) return null;
  return (
    // @container: four KPI cards a row only when the column (not the window) is wide enough, as ChartGrid does
    <section data-testid="overview" aria-labelledby="overview-title" className="@container grid gap-2.5">
      <h2 id="overview-title" className="text-[13px] text-muted-foreground">
        <span className="section-label">Overview</span> · Last 30 days · as of {data.as_of}
      </h2>
      <div className="grid grid-cols-2 gap-2.5 @2xl:grid-cols-4">
        {data.kpis.map((k, i) => (
          <KpiCard key={k.key} k={k} i={i} />
        ))}
      </div>
      <ChartCard
        chart={data.trend}
        i={data.kpis.length}
        // a day's point carries `_ask`, the question Python built; the line and last period's points carry none
        onDatumClick={(d) => typeof d._ask === "string" && askWhy(d._ask)}
        caption={
          <span data-testid="trend-caption" className="flex flex-wrap items-center gap-x-2 gap-y-1">
            Click a day to ask why it moved{data.days.length > 0 ? ", or pick one:" : "."}
            {/* the keyboard's way to any point: the chart's svg takes no focus. Never holds a value: each pick asks */}
            {data.days.length > 0 && (
              <Select value="" onValueChange={askWhy}>
                <SelectTrigger
                  size="sm"
                  data-testid="ask-day"
                  aria-label="Ask why a day moved"
                  className="text-foreground data-[size=sm]:h-6"
                >
                  <SelectValue placeholder="Pick a day" />
                </SelectTrigger>
                <SelectContent position="popper" className="max-h-72">
                  {data.days.map((d) => (
                    <SelectItem key={d.question} value={d.question}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {data.unusual.length > 0 && (
              <>
                <span>Unusual days:</span>
                {data.unusual.map((u) => (
                  <button
                    key={u.question}
                    type="button"
                    data-testid="unusual-day"
                    title={u.question}
                    onClick={() => askWhy(u.question)}
                    className="inline-flex min-h-6 items-center gap-1.5 rounded-full border px-2 font-medium text-foreground tabular-nums transition-colors outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <span aria-hidden className="size-2 rounded-full bg-negative" />
                    <span className="sr-only">Ask why it moved: </span>
                    {u.label}
                  </button>
                ))}
              </>
            )}
          </span>
        }
      />
    </section>
  );
}
