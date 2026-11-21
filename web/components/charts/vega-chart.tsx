"use client";

import { Download } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { Result, VisualizationSpec } from "vega-embed";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import COLORS from "@/lib/chart-colors.json";
import { chartTheme, type ChartTheme } from "@/lib/chart-theme";
import { subscribeTheme } from "@/lib/theme";

type Spec = { [key: string]: unknown };
type VegaEmbed = typeof import("vega-embed");
type Datum = Record<string, unknown>;
type ChartProps = {
  spec: Spec;
  /** Called with the datum of a clicked mark. A drillable datum carries `_ask`, the question Python built. */
  onDatumClick?: (datum: Datum) => void;
  /** When set, a "Download PNG" button (on hover and focus) saves the chart as `<downloadName>.png`. */
  downloadName?: string;
};

const MAPS = { light: new Map(Object.entries(COLORS.light)), dark: new Map(Object.entries(COLORS.dark)) };
const isDark = () => document.documentElement.classList.contains("dark");

/** A deep copy of `v` in which every string equal (any case) to a key of `map` becomes that key's value. */
function recolor(v: unknown, map: Map<string, string>): unknown {
  if (typeof v === "string") return map.get(v.toUpperCase()) ?? v;
  if (Array.isArray(v)) return v.map((x) => recolor(x, map));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, recolor(x, map)]));
  return v;
}

function Chart({ spec, lib, onDatumClick, downloadName }: ChartProps & { lib: VegaEmbed }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme: ChartTheme = useSyncExternalStore(subscribeTheme, isDark, () => false) ? "dark" : "light";
  const [failed, setFailed] = useState<{ spec: Spec; message: string } | null>(null);
  const [drawn, setDrawn] = useState<{ spec: Spec; theme: ChartTheme; view: Result["view"] } | null>(null);
  // The latest handler, so a new callback identity never re-embeds the chart
  const onClick = useRef(onDatumClick);
  useEffect(() => {
    onClick.current = onDatumClick;
  });

  useEffect(() => {
    const copy = recolor(spec, MAPS[theme]) as Spec;
    delete copy.$schema; // charts.py says Vega-Lite v5; vega-embed would warn that it runs v6
    // Every charts.py spec is 620 px wide, wider than the rail: fit the container instead (spec: Charts).
    // ponytail: Vega re-reads the container width on window resize only, not when the rail is dragged.
    copy.width = "container";
    // A fresh element per embed, so a slow earlier embed never draws over this one. It stays transparent until
    // Vega has drawn, then fades and scales in (globals.css chart-in; instant under reduced motion).
    const el = document.createElement("div");
    el.style.opacity = "0";
    const width = ref.current!.clientWidth;
    ref.current!.replaceChildren(el);
    const config = chartTheme(theme);
    // Vega never wraps a title: on a narrow column a long one ends in an ellipsis instead of running off the card
    if (width > 0) config.title = { ...config.title, limit: width };
    let done: (() => void) | undefined;
    let live = true;
    lib
      .default(el, copy as VisualizationSpec, {
        actions: false,
        renderer: "svg",
        config,
        tooltip: { theme },
        // Errors only: a container width with a step height (the waterfall) makes Vega-Lite warn
        // 'Dropping "fit-y"' on every render, though "fit-x" is what it keeps and what is wanted.
        logLevel: lib.vega.Error,
      })
      .then(
        (r) => {
          if (!live) return r.finalize();
          done = r.finalize;
          r.view.addEventListener("click", (_e, item) => {
            if (item?.datum) onClick.current?.(item.datum as Datum);
          });
          setDrawn({ spec, theme, view: r.view });
          el.style.opacity = "";
          el.classList.add("animate-chart-in");
        },
        (e) => {
          if (live) setFailed({ spec, message: e instanceof Error ? e.message : String(e) });
        },
      );
    return () => {
      live = false;
      done?.();
      el.remove();
    };
  }, [spec, theme, lib]);

  const view = drawn?.spec === spec && drawn.theme === theme ? drawn.view : null;
  async function download() {
    if (!view) return;
    // The theme draws on transparent; the PNG gets the card colour so dark-theme text stays legible in a viewer.
    const bg = view.background();
    view.background(getComputedStyle(ref.current!).getPropertyValue("--card").trim() || "white");
    const a = document.createElement("a");
    a.href = await view.toImageURL("png", 2);
    view.background(bg).runAsync();
    a.download = `${downloadName}.png`;
    a.click();
  }

  return (
    <div className="group/chart relative min-w-0">
      <div ref={ref} className="w-full min-w-0" />
      {failed?.spec === spec && (
        <p className="text-xs text-muted-foreground wrap-anywhere">This chart could not be drawn: {failed.message}</p>
      )}
      {/* After the chart in the DOM, and only once it has drawn, so its icon is never taken for the chart's svg */}
      {downloadName && view && (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Download PNG"
          title="Download PNG"
          onClick={download}
          className="absolute top-0 right-0 bg-card/80 text-muted-foreground transition-opacity pointer-fine:opacity-0 pointer-fine:group-hover/chart:opacity-100 pointer-fine:focus-visible:opacity-100"
        >
          <Download />
        </Button>
      )}
    </div>
  );
}

/** A Vega-Lite spec drawn on the client only; vega-embed loads lazily. Colours follow the theme through
 * chart-colors.json and re-render when it changes. */
export const VegaChart = dynamic(
  () =>
    import("vega-embed").then((lib) => {
      function LoadedChart(props: ChartProps) {
        return <Chart {...props} lib={lib} />;
      }
      return LoadedChart;
    }),
  { ssr: false, loading: () => <Skeleton className="h-48 w-full" /> },
);
