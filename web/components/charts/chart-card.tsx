import type { CSSProperties, ReactNode } from "react";

import { VegaChart } from "@/components/charts/vega-chart";
import type { ChartView } from "@/lib/api";

/** A dashboard chart (Home, Eval, Runs) on a card that rises in at stagger step `i`. The spec draws its own
 * title; `summary` is the text alternative, and the drawing itself is hidden from assistive tech (the download button
 * and caption are not). `onDatumClick` and `downloadName` pass through to VegaChart; `caption` goes under the chart. */
export function ChartCard({
  chart,
  i = 0,
  onDatumClick,
  downloadName,
  caption,
}: {
  chart: ChartView;
  i?: number;
  onDatumClick?: (datum: Record<string, unknown>) => void;
  downloadName?: string;
  caption?: ReactNode;
}) {
  return (
    <figure
      // An img's children are presentational, which would hide the download button and caption from assistive tech
      role={downloadName || caption ? undefined : "img"}
      aria-label={chart.summary}
      data-testid="chart-card"
      data-chart={chart.key}
      style={{ "--i": i } as CSSProperties}
      className="rise min-w-0 rounded-xl border bg-card p-3.5 shadow-sm"
    >
      <VegaChart spec={chart.spec} onDatumClick={onDatumClick} downloadName={downloadName} decorative />
      {caption && <figcaption className="mt-1.5 text-xs text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}

/** Dashboard charts side by side once their column is wide enough (a container query, so the rail or a narrow
 * centre gets one column), else stacked. Each card keeps its own height, so a short chart leaves no empty card. */
export function ChartGrid({ charts, from = 0 }: { charts: ChartView[]; from?: number }) {
  if (!charts.length) return null;
  return (
    <div className="@container">
      <div data-testid="chart-grid" className="grid items-start gap-2.5 @2xl:grid-cols-2">
        {charts.map((c, j) => (
          <ChartCard key={c.key} chart={c} i={from + j} />
        ))}
      </div>
    </div>
  );
}
