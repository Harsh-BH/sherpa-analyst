import type { Config } from "vega-lite";

export type ChartTheme = "light" | "dark";

// The UI tokens (globals.css) the chart chrome uses.
const TOKENS = {
  light: { text: "#111214", muted: "#5A5E66", border: "#E1E2E5", accent: "#2456C4" },
  dark: { text: "#EDEEF0", muted: "#9A9EA7", border: "#25272C", accent: "#7FA8FF" },
};

/** Vega config for everything around the data: transparent, Geist, axes and legends in the UI's greys.
 * Data colours come from the spec, recoloured through chart-colors.json. */
export function chartTheme(theme: ChartTheme): Config {
  const t = TOKENS[theme];
  const labels = { labelColor: t.muted, titleColor: t.muted };
  return {
    background: "transparent",
    font: 'Geist, "Geist Fallback", sans-serif',
    view: { stroke: null },
    title: { color: t.text, subtitleColor: t.muted, anchor: "start" },
    axis: { ...labels, gridColor: t.border, domainColor: t.border, tickColor: t.border },
    legend: labels,
    mark: { color: t.accent }, // single-series marks, which the spec leaves to Vega's default blue
    text: { fill: t.text },
    rule: { color: t.muted },
  };
}
