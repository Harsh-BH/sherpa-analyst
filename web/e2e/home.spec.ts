import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

const HEAD = "Business head (all regions)";
type Row = { series: string; _ask?: string };

async function open(page: Page, url = "/") {
  await page.goto(url);
  await expect(page.getByTestId("persona")).toHaveText(HEAD);
}

/** The questions posted to /api/ask, in order. */
const askedQuestions = (page: Page) => {
  const qs: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/ask") qs.push(JSON.parse(r.postData() ?? "{}").question);
  });
  return qs;
};

test("home rail: data health rows, how Sherpa answers and the eval line; a row asks", async ({ page }) => {
  const dh = fixture("data_health");
  const asked = askedQuestions(page);
  await open(page);
  const rail = page.getByTestId("rail");
  const rows = rail.getByTestId("data-health-row");
  await expect(rows).toHaveCount(dh.issues.length);
  for (const [i, issue] of dh.issues.entries()) {
    await expect(rows.nth(i)).toContainText(issue.when);
    await expect(rows.nth(i)).toContainText(issue.text);
    await expect(rows.nth(i)).toHaveAttribute("data-severity", issue.severity);
  }
  await expect(rail).toContainText("How Sherpa answers");
  const proof = rail.getByTestId("eval-proof");
  await expect(proof).toHaveText(/^Eval: \d+\/\d+ cases vs \d+\/\d+ for a naive baseline$/);
  await expect(proof).toHaveAttribute("href", "/eval");

  await rows.first().click();
  await expect(page.getByTestId("trace")).toBeVisible();
  await expect(page.getByTestId("question")).toHaveValue(dh.issues[0].question);
  await expect.poll(() => asked).toEqual([dh.issues[0].question]);
  // the answer replaces the home rail with its own inspector
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(rail.getByTestId("home-rail")).toHaveCount(0);
});

test("data health says so when the window is clean, and hides for a persona the fixture is not", async ({ page }) => {
  await page.route("**/api/data-health?*", (r) =>
    r.fulfill({ json: { available: true, persona: "head", window: "last 30 days", issues: [] } }),
  );
  await open(page);
  const rail = page.getByTestId("rail");
  await expect(rail.getByTestId("data-health-empty")).toHaveText("No data-quality issues in the last 30 days");
  await page.unroute("**/api/data-health?*");
  await page.getByTestId("persona").click();
  await page.getByRole("option", { name: "Regional manager, South" }).click();
  // the fixture is head's: South gets no section rather than head's all-region issues
  await expect(rail.getByTestId("data-health-loading")).toHaveCount(0);
  await expect(rail.getByTestId("data-health")).toHaveCount(0);
  await expect(rail).toContainText("How Sherpa answers");
});

test("clicking a day on the trend asks why it moved", async ({ page }) => {
  const days: Row[] = fixture("overview").trend.spec.data.values.filter((r: Row) => r.series === "Last 30 days");
  const asked = askedQuestions(page);
  await open(page);
  const card = page.getByTestId("overview").getByTestId("chart-card");
  await expect(card.getByTestId("trend-caption")).toContainText("Click a day to ask why it moved");
  const points = card.locator("g.ask_points_marks path");
  await expect(points).toHaveCount(days.length);
  await points.last().click();
  await expect(page.getByTestId("trace")).toBeVisible();
  await expect(page.getByTestId("question")).toHaveValue(days.at(-1)!._ask!);
  await expect(page.getByTestId("question")).toHaveValue(
    /^Why did success rate (fall|rise) on \d{1,2} [A-Z][a-z]{2} compared with the day before\?$/,
  );
  await expect.poll(() => asked.length).toBe(1);
});

test("an unusual day is a keyboard-reachable button that asks", async ({ page }) => {
  const unusual: { label: string; question: string }[] = fixture("overview").unusual;
  test.skip(!unusual.length, "the overview fixture flags no unusual day");
  await open(page);
  const button = page.getByTestId("unusual-day").first();
  await expect(button).toContainText(unusual[0].label);
  await button.press("Enter");
  await expect(page.getByTestId("trace")).toBeVisible();
  await expect(page.getByTestId("question")).toHaveValue(unusual[0].question);
});
