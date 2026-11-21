import type { Config } from "vega-lite";

export type ChartTheme = "light" | "dark";

// The UI tokens (globals.css) the chart chrome uses. `muted` is AA on both the card and the page bg.
const TOKENS = {
  light: { text: "#111214", muted: "#5A5E66", border: "#E1E2E5", accent: "#2456C4" },
  dark: { text: "#ECEEF2", muted: "#9CA2AE", border: "#23262E", accent: "#8AB4FF" },
};

/** Vega config for everything around the data: transparent, Geist, axes and legends in the UI's greys, a soft
 * grid, rounded bar ends. Data colours come from the spec, recoloured through chart-colors.json. */
export function chartTheme(theme: ChartTheme): Config {
  const t = TOKENS[theme];
  const labels = { labelColor: t.muted, titleColor: t.muted, labelFontSize: 11, titleFontSize: 11, titleFontWeight: 500 } as const;
  return {
    background: "transparent",
    font: 'Geist, "Geist Fallback", sans-serif',
    view: { stroke: null },
    title: { color: t.text, subtitleColor: t.muted, anchor: "start", fontSize: 13, fontWeight: 600 },
    axis: { ...labels, gridColor: t.border, gridOpacity: 0.6, domainColor: t.border, tickColor: t.border, labelPadding: 4 },
    legend: labels,
    mark: { color: t.accent }, // single-series marks, which the spec leaves to Vega's default blue
    bar: { cornerRadiusEnd: 3 },
    text: { fill: t.text },
    rule: { color: t.muted },
  };
}
