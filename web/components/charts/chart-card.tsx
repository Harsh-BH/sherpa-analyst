import type { CSSProperties } from "react";

import { VegaChart } from "@/components/charts/vega-chart";
import type { ChartView } from "@/lib/api";

/** A dashboard chart (Home, Eval, Runs) on a card that rises in at stagger step `i`. The spec draws its own
 * title; `summary` is the text alternative. */
export function ChartCard({ chart, i = 0 }: { chart: ChartView; i?: number }) {
  return (
    <figure
      role="img"
      aria-label={chart.summary}
      data-testid="chart-card"
      data-chart={chart.key}
      style={{ "--i": i } as CSSProperties}
      className="rise min-w-0 rounded-xl border bg-card p-3.5 shadow-sm"
    >
      <VegaChart spec={chart.spec} />
    </figure>
  );
}

/** Dashboard charts side by side once their column is wide enough (a container query, so the rail or a narrow
 * centre gets one column), else stacked. */
export function ChartGrid({ charts, from = 0 }: { charts: ChartView[]; from?: number }) {
  if (!charts.length) return null;
  return (
    <div className="@container">
      <div data-testid="chart-grid" className="grid gap-2.5 @2xl:grid-cols-2">
        {charts.map((c, j) => (
          <ChartCard key={c.key} chart={c} i={from + j} />
        ))}
      </div>
    </div>
  );
}
