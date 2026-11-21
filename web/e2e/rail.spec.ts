import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

const EXPLAIN = "Why did success rate drop last week?";
const SQL_Q = "Which merchants had the most failed payments last week?";
const RECON = "Why doesn't settled amount match GMV for the last 7 days?";

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
}

async function ask(page: Page, question: string) {
  await page.getByTestId("question").fill(question);
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("headline")).toBeVisible();
}

/** Every claim citing `id` is highlighted, and no other claim is. */
async function expectHighlighted(page: Page, id: string) {
  const claims = await page.getByTestId("claim").all();
  expect(claims.length).toBeGreaterThan(0);
  for (const c of claims) {
    const cites = (await c.getAttribute("data-cites"))!.split(" ");
    await expect(c).toHaveAttribute("data-highlight", String(cites.includes(id)));
  }
}

/** The real sql_route answer, stretched: a 300-character SQL line and a 200-row table of long merchant names. */
async function stretchSqlRoute(page: Page) {
  await page.route("**/api/ask", async (route) => {
    const res = await route.fetch();
    const body = await res.text();
    const data = /^event: result\r?\ndata: (.*)$/m.exec(body)![1];
    const result = JSON.parse(data);
    const e = result.view.evidence[0];
    e.sql[0].value += `\n-- ${"x".repeat(300)}`;
    e.table.rows = Array.from({ length: 200 }, (_, i) => [`${"Long merchant name ".repeat(12)}${i}`, `M${i}`, "1"]);
    await route.fulfill({ response: res, body: body.replace(data, () => JSON.stringify(result)) });
  });
}

test("chip opens evidence in the rail and highlights citing claims", async ({ page }) => {
  await open(page);
  await ask(page, EXPLAIN);
  await page.getByTestId("chip-E2").first().click();
  const e2 = page.getByTestId("evidence-E2");
  await expect(e2).toHaveAttribute("data-selected", "true");
  await expect(e2).toContainText("SELECT");
  await expect(e2).toContainText("Cited by claim 2, 3, 4");
  await expectHighlighted(page, "E2");

  // The other way round: selecting a rail entry highlights the claims that cite it.
  await page.getByTestId("evidence-E1").getByRole("button", { name: /^E1/ }).click();
  await expect(page.getByTestId("evidence-E1")).toHaveAttribute("data-selected", "true");
  await expect(e2).toHaveAttribute("data-selected", "false");
  await expectHighlighted(page, "E1");

  // A chip brings the Evidence tab back, even for the entry already selected.
  await page.getByRole("tab", { name: "Plan" }).click();
  await expect(page.getByTestId("rail")).toContainText("explain_change");
  await page.getByTestId("chip-E1").first().click();
  await expect(page.getByTestId("evidence-E1")).toHaveAttribute("data-selected", "true");
});

test("charts render", async ({ page }) => {
  await open(page);
  await ask(page, EXPLAIN);
  await expect(page.getByTestId("simpson")).toContainText("Simpson");
  await page.getByTestId("chip-E2").first().click();
  await expect(page.getByTestId("key-chart").locator("svg.marks")).toBeVisible();
  await expect(page.getByTestId("evidence-E2").locator("svg.marks")).toBeVisible();
  expect(await page.locator("svg.marks:visible").count()).toBeGreaterThanOrEqual(2);
});

test("decompose by switches the chart", async ({ page }) => {
  await open(page);
  await ask(page, EXPLAIN);
  const chart = page.getByTestId("key-chart").locator("svg.marks");
  await expect(chart).toContainText("Mix vs rate by payment method");
  await expect(page.getByTestId("simpson")).toBeVisible();
  await page.getByTestId("decompose").click();
  await page.getByRole("option").nth(1).click();
  await expect(chart).toContainText("Mix vs rate by gateway");
  await expect(page.getByTestId("simpson")).toHaveCount(0);
  await expect(page.getByTestId("key-summary")).toContainText("By gateway");
});

test("reconcile renders bridge and components", async ({ page }) => {
  await open(page);
  await ask(page, RECON);
  await expect(page.getByText("Reconciliation components")).toBeVisible();
  await expect(page.getByTestId("recon")).toContainText("Source of truth");
  await expect(page.getByTestId("key-chart").locator("svg.marks")).toBeVisible();
});

test("sql_route table shows injection verbatim", async ({ page }) => {
  const injection: string = fixture("sql_route").evidence[0].table[1].display_name;
  await open(page);
  const images = () => page.evaluate(() => document.querySelectorAll("img").length);
  const before = await images();
  await ask(page, SQL_Q);
  await page.getByTestId("chip-E1").first().click();
  const e1 = page.getByTestId("evidence-E1");
  await expect(e1.getByRole("cell", { name: injection, exact: true })).toBeVisible();
  await expect(e1.locator("svg.marks")).toBeVisible();
  expect(await images()).toBe(before);
});

test("no page overflow on sql_route", async ({ page }) => {
  await stretchSqlRoute(page);
  for (const width of [1400, 1100]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    await ask(page, SQL_Q);
    await page.getByTestId("chip-E1").first().click();
    await expect(page.getByTestId("evidence-E1").locator("svg.marks")).toBeVisible();
    await expect(page.getByTestId("evidence-E1")).toContainText("x".repeat(300));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // Neither pane scrolls sideways: long SQL and tables scroll inside their own blocks, charts fit the rail.
    const sideways = await page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>(".overflow-y-auto")]
        .filter((e) => e.scrollWidth > e.clientWidth)
        .map((e) => e.className),
    );
    expect(sideways, `at ${width} px`).toEqual([]);
  }
});

test("narrow screen: chip opens the sheet", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await open(page);
  await ask(page, EXPLAIN);
  await page.getByTestId("chip-E2").first().click();
  const sheet = page.getByTestId("rail-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByTestId("evidence-E2")).toHaveAttribute("data-selected", "true");
  const header = sheet.getByTestId("evidence-E2").getByRole("button", { name: /^E2/ });
  await expect(header).toBeInViewport();
  // scrolled to, not under the sticky tab bar
  const hit = await header.evaluate((b) => {
    const r = b.getBoundingClientRect();
    return b.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 4));
  });
  expect(hit).toBe(true);
});

test("dark theme recolours charts", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await open(page);
  await ask(page, RECON); // the bridge draws "Reduces payout" in DOWN #D55E00
  const marks = page.getByTestId("key-chart").locator("svg.marks");
  await expect(marks.locator('[fill="#C22F2A"]').first()).toBeAttached(); // light --negative
  const toggle = page.getByTestId("theme-toggle");
  await toggle.click(); // system -> light
  await toggle.click(); // light -> dark
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await expect(marks.locator('[fill="#FF7B74"]').first()).toBeAttached(); // dark --negative
  await expect(page.locator('svg.marks [fill="#D55E00"]')).toHaveCount(0);
  await expect(page.locator('svg.marks [fill="#C22F2A"]')).toHaveCount(0);
});
