import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Track D (fixture mode): follow-ups, waterfall drill, copy and PNG, headline chips, wide tables.
const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

const EXPLAIN = "Why did success rate drop last week?";
const HEAD = "Business head (all regions)";

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("persona")).toHaveText(HEAD);
}

/** Ask and wait for this answer (not the previous one, which the click unmounts before the request leaves). */
async function ask(page: Page, question: string) {
  await page.getByTestId("question").fill(question);
  await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === "/api/ask"),
    page.getByTestId("ask-button").click(),
  ]);
  await expect(page.getByTestId("headline")).toBeVisible();
}

const askBodies = (page: Page) => {
  const bodies: Record<string, unknown>[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/ask") bodies.push(JSON.parse(r.postData() ?? "{}"));
  });
  return bodies;
};

test("follow-up chips render and a click asks the question with its plan", async ({ page }) => {
  const bodies = askBodies(page);
  await open(page);
  await ask(page, EXPLAIN);
  const chips = page.getByTestId("follow-up");
  await expect(chips.first()).toBeVisible();
  expect(await chips.count()).toBeGreaterThanOrEqual(2);
  await expect(chips.first()).toHaveText("UPI by gateway");
  const question = (await chips.first().getAttribute("title"))!;
  expect(question).toMatch(/^Why did success rate change for payment method UPI, by gateway, /);
  await chips.first().click();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toMatchObject({ question, persona: "head", plan: { intent: "explain_change", dimensions: ["gateway"] } });
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.getByTestId("question")).toHaveValue(question);
});

test("waterfall segments drill: a segment button asks why it moved", async ({ page }) => {
  const bodies = askBodies(page);
  await open(page);
  await ask(page, EXPLAIN);
  await expect(page.getByTestId("key-chart").locator("svg.marks")).toBeVisible();
  const drill = page.getByTestId("drill");
  await expect(drill.getByRole("button")).toHaveText(["UPI", "CARD"]);
  await drill.getByRole("button", { name: "UPI" }).click();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1].question).toBe("Why did success rate change for payment method UPI in the last 7 days (13-19 Nov 2026)?");
  expect(bodies[1].plan).toBeUndefined(); // a bar's question goes through the planner, like a typed one
  await expect(page.getByTestId("headline")).toBeVisible();
});

test("headline numbers are chips and the sentence reads the same", async ({ page }) => {
  await open(page);
  await ask(page, EXPLAIN);
  const headline = page.getByTestId("headline");
  await expect(headline).toHaveText(fixture("explain_change").headline);
  const down = headline.locator('[data-kind="down"]');
  await expect(down).toHaveText("-1.10 pp");
  await expect(down).toHaveAttribute("data-tone", "negative");
  await expect(headline.locator('[data-kind="value"]')).toHaveText(["92.8%", "91.7%"]);
});

test("copy answer copies the Markdown and shows Copied", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  await ask(page, EXPLAIN);
  const copy = page.getByTestId("copy-answer");
  await expect(copy).toHaveText("Copy answer");
  await copy.click();
  await expect(copy).toHaveText("Copied");
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text.startsWith(`## ${fixture("explain_change").headline}`)).toBe(true);
  expect(text).toContain("fx-explain-0001");
  await expect(copy).toHaveText("Copy answer"); // back after 1.5 s
});

test("each answer chart downloads as a PNG", async ({ page }) => {
  await open(page);
  await ask(page, EXPLAIN);
  const chart = page.getByTestId("key-chart");
  await expect(chart.locator("svg.marks")).toBeVisible();
  await chart.locator("svg.marks").hover();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    chart.getByRole("button", { name: "Download PNG" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("sherpa-run-fx-explain-0001-payment_method.png");

  // and every evidence chart in the rail, named by its evidence id
  await page.getByTestId("chip-E2").first().click();
  const e2 = page.getByTestId("evidence-E2");
  await expect(e2.locator("svg.marks")).toBeVisible();
  await e2.locator("svg.marks").hover();
  const [evidence] = await Promise.all([
    page.waitForEvent("download"),
    e2.getByRole("button", { name: "Download PNG" }).click(),
  ]);
  expect(evidence.suggestedFilename()).toBe("sherpa-run-fx-explain-0001-E2.png");
});

test("driver tables show key columns; More columns toggles and is remembered", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await ask(page, EXPLAIN);
  const table = page.getByTestId("drivers").locator("table").first();
  const headers = table.getByRole("columnheader");
  await expect(headers).toHaveText(["segment", "share before", "share now", "rate before", "rate now", "total (pp)"]);
  // the default columns fit: the table's box does not scroll sideways
  const wrap = table.locator("xpath=..");
  expect(await wrap.evaluate((e) => e.scrollWidth <= e.clientWidth)).toBe(true);

  const more = page.getByTestId("more-columns").first();
  await expect(more).toHaveText("More columns (7)");
  await more.click();
  await expect(headers).toHaveCount(13);
  await expect(more).toHaveAttribute("aria-expanded", "true");
  // the first column stays put when the table scrolls sideways
  expect(await headers.first().evaluate((e) => getComputedStyle(e).position)).toBe("sticky");

  await ask(page, EXPLAIN); // the choice holds for the next answer in this session
  await expect(page.getByTestId("drivers").locator("table").first().getByRole("columnheader")).toHaveCount(13);
  await page.getByTestId("more-columns").first().click();
  await expect(page.getByTestId("drivers").locator("table").first().getByRole("columnheader")).toHaveCount(6);
});
