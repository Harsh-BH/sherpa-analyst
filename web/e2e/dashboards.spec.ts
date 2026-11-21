import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

const HEAD = "Business head (all regions)";

async function open(page: Page, url = "/") {
  await page.goto(url);
  await expect(page.getByTestId("persona")).toHaveText(HEAD);
}

/** A chart card has a text alternative and, once Vega has drawn, an svg. */
async function expectDrawn(card: Locator) {
  await expect(card).toHaveAttribute("aria-label", /\w{3,}/);
  await expect(card.locator("svg").first()).toBeVisible();
}

const color = (l: Locator) => l.evaluate((el) => getComputedStyle(el).color);
const token = (page: Page, name: string) =>
  page.evaluate((n) => {
    const probe = document.createElement("span");
    probe.style.color = `var(${n})`;
    document.body.append(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  }, name);

test("home overview: four KPI cards with sparklines and the trend chart", async ({ page }) => {
  const ov = fixture("overview");
  await open(page);
  const panel = page.getByTestId("overview");
  await expect(panel).toContainText(`Last 30 days · as of ${ov.as_of}`);
  const cards = panel.getByTestId("kpi-card");
  await expect(cards).toHaveCount(ov.kpis.length);
  await expect(cards.getByTestId("kpi-value")).toHaveText(ov.kpis.map((k: { value: string }) => k.value));
  await expect(cards.getByTestId("kpi-delta")).toHaveText(ov.kpis.map((k: { delta: string }) => k.delta));
  for (const card of await cards.all()) await expect(card.getByRole("img").locator("svg")).toBeVisible();
  // the delta takes the metric's tone: success rate fell (bad), technical decline rate fell (good)
  const tone = (key: string) => color(cards.nth(ov.kpis.findIndex((k: { key: string }) => k.key === key)).getByTestId("kpi-delta"));
  expect(await tone("success_rate")).toBe(await token(page, "--negative"));
  expect(await tone("technical_decline_rate")).toBe(await token(page, "--positive"));
  await expectDrawn(panel.getByTestId("chart-card"));
  // above the example questions, and gone once a question is asked
  const chipsTop = (await page.getByTestId("demo-chip").first().boundingBox())!.y;
  expect((await panel.boundingBox())!.y).toBeLessThan(chipsTop);
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.getByTestId("overview")).toHaveCount(0);
});

test("home overview is hidden when the API says it is unavailable", async ({ page }) => {
  await page.route("**/api/overview?*", (r) => r.fulfill({ json: { available: false, reason: "no DB" } }));
  await open(page);
  await expect(page.getByTestId("demo-chip").first()).toBeVisible();
  await expect(page.getByTestId("overview-loading")).toHaveCount(0);
  await expect(page.getByTestId("overview")).toHaveCount(0);
});

test("switching persona refetches the overview", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname === "/api/overview") asked.push(u.searchParams.get("persona") ?? "");
  });
  await open(page);
  await expect(page.getByTestId("overview")).toBeVisible();
  await page.getByTestId("persona").click();
  await page.getByRole("option", { name: "Regional manager, South" }).click();
  await expect.poll(() => asked).toEqual(["head", "rm_south"]);
  // the fixture is head's: South gets no panel rather than head's all-region numbers
  await expect(page.getByTestId("overview-loading")).toHaveCount(0);
  await expect(page.getByTestId("overview")).toHaveCount(0);
});

test("eval charts sit above the cases, and Pass/Fail are coloured", async ({ page }) => {
  await page.goto("/eval");
  const charts = page.getByTestId("chart-card");
  await expect(charts).toHaveCount(2);
  await expect(charts.nth(0)).toHaveAttribute("aria-label", /^Sherpa vs baseline: /);
  await expect(charts.nth(1)).toHaveAttribute("aria-label", /^Pass rate by question type: /);
  for (const c of await charts.all()) await expectDrawn(c);
  const tableTop = (await page.getByTestId("eval-cases").boundingBox())!.y;
  expect((await charts.last().boundingBox())!.y).toBeLessThan(tableTop);
  const verdicts = page.getByTestId("eval-cases").getByTestId("verdict");
  const pass = verdicts.and(page.locator("[data-pass=true]")).first();
  await expect(pass).toHaveText("Pass");
  expect(await color(pass)).toBe(await token(page, "--positive"));
  const fail = verdicts.and(page.locator("[data-pass=false]")).first();
  if (await fail.count()) expect(await color(fail)).toBe(await token(page, "--negative"));
});

const TILES = ["Runs", "p50 latency", "LLM cost", "Refusal rate", "Clarify rate", "Cache hit rate", "Errors"].map(
  (label) => ({ label, value: "n/a" }),
);
const run = (status: string, i: number) => ({
  run_id: `r${i}`,
  asked_at: "21 Nov 2026 16:0" + i,
  persona: "head",
  question: `question ${i}`,
  status,
  route: "explain",
  confidence: "high",
  total: "4.2 s",
  cost: "$0.0100",
  footprint: [{ label: "LLM", value: "template" }],
});
const BARS = {
  key: "runs-over-time",
  title: "Runs over time",
  summary: "4 runs: 1 answered, 1 clarify, 1 refused, 1 error, by hour.",
  spec: {
    data: { values: [{ status: "answered", n: 1 }, { status: "clarify", n: 1 }] },
    mark: "bar",
    encoding: { x: { field: "status", type: "nominal" }, y: { field: "n", type: "quantitative" } },
  },
};

test("runs: note, charts above the table and coloured status badges", async ({ page }) => {
  const statuses = ["answered", "clarify", "refused", "error"];
  await page.route("**/api/runs", (r) =>
    r.fulfill({ json: { status: "ok", tiles: TILES, recent: statuses.map(run), charts: [BARS] } }),
  );
  await page.goto("/runs");
  await expect(page.getByTestId("runs-note")).toHaveText("Runs asked in the app. Test and eval runs are excluded.");
  const chart = page.getByTestId("chart-card");
  await expect(chart).toHaveCount(1);
  await expect(chart).toHaveAttribute("aria-label", BARS.summary);
  await expectDrawn(chart);
  expect((await chart.boundingBox())!.y).toBeLessThan((await page.getByTestId("runs-table").boundingBox())!.y);
  const badges = page.getByTestId("run-status");
  await expect(badges).toHaveText(statuses);
  expect(await color(badges.nth(0))).toBe(await token(page, "--positive"));
  expect(await color(badges.nth(1))).toBe(await token(page, "--warning"));
  expect(await color(badges.nth(3))).toBe(await token(page, "--destructive"));
  await expect(page.getByTestId("runs-empty")).toHaveCount(0);
});

test("runs: with no app runs, an empty state and no charts", async ({ page }) => {
  await page.route("**/api/runs", (r) => r.fulfill({ json: { status: "ok", tiles: TILES, recent: [], charts: [] } }));
  await page.goto("/runs");
  await expect(page.getByTestId("runs-empty")).toContainText("No runs yet. Ask a question and it shows up here.");
  await expect(page.getByTestId("chart-card")).toHaveCount(0);
  await expect(page.getByTestId("runs-table")).toHaveCount(0);
  await expect(page.getByTestId("run-tile")).toHaveCount(7);
});

test("expanded trace lists as many stages as its step count, each with a timing bar", async ({ page }) => {
  await open(page);
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();
  const trace = page.getByTestId("trace");
  await expect(trace).toContainText(/\d+ steps/);
  const steps = Number(/(\d+) steps/.exec((await trace.textContent())!)![1]);
  await trace.getByRole("button").click();
  const rows = trace.getByTestId("trace-stage");
  await expect(rows).toHaveCount(steps);
  // explain_change: plan 2100 and narrate 3200 of a 5600 ms total
  const bars = trace.getByTestId("stage-bar");
  await expect(bars).toHaveCount(steps);
  const widths = await bars.evaluateAll((els) => els.map((e) => parseFloat((e as HTMLElement).style.width)));
  expect(widths[0]).toBeCloseTo(37.5, 3);
  expect(widths[1]).toBeCloseTo((3200 / 5600) * 100, 3);
  expect(await bars.first().evaluate((e) => getComputedStyle(e).animationName)).toBe("grow");
  await expect(rows.first()).toHaveText(/^Plan\s*2\.1 s$/);
});
