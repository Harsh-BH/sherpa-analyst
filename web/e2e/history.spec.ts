import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Fixture mode: /api/history and /api/runs/{id} serve the persona's fixture bundles (app.backend.fixture_runs).
const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

const HEAD = "Business head (all regions)";
const HEAD_RUNS = ["fx-explain-0001", "fx-recon-0001", "fx-sql-0001", "fx-clarify-0001", "fx-error-0001"];

async function open(page: Page, url = "/") {
  await page.goto(url);
  await expect(page.getByTestId("persona")).toHaveText(HEAD);
}

const recent = (page: Page) => page.getByTestId("recent").getByTestId("recent-run");

test("Recent lists the persona's runs; clicking one reopens it with no stages streamed", async ({ page }) => {
  await open(page);
  await expect(recent(page)).toHaveCount(HEAD_RUNS.length);
  expect(await recent(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-run-id")))).toEqual(HEAD_RUNS);
  // the status is in the name, not only in the dot's colour
  await expect(recent(page).first()).toHaveAccessibleName(`answered: ${fixture("explain_change").question}`);

  await recent(page).nth(1).click();
  await expect(page.getByTestId("headline")).toHaveText(fixture("reconcile").headline);
  await expect(page).toHaveURL(/\/\?run=fx-recon-0001$/);
  await expect(recent(page).nth(1)).toHaveAttribute("data-active", "true");
  const trace = page.getByTestId("trace");
  await expect(trace).toHaveAttribute("data-stage-times", "[]"); // a stored run: the footprint, no live stages
  await expect(trace).not.toHaveAttribute("aria-busy", "true");
});

test("Recent opens the run from another page", async ({ page }) => {
  await open(page, "/runs");
  await recent(page).nth(2).click();
  await expect(page).toHaveURL(/\/\?run=fx-sql-0001$/);
  await expect(page.getByTestId("headline")).toHaveText(fixture("sql_route").headline);
});

test("a permalink opens its run on load, and a new question drops it from the URL", async ({ page }) => {
  await open(page, "/?run=fx-sql-0001");
  await expect(page.getByTestId("headline")).toHaveText(fixture("sql_route").headline);
  await expect(page.getByTestId("badge-route")).toHaveText("Unverified SQL");
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("headline")).toHaveText(fixture("explain_change").headline);
  await expect(page).toHaveURL(/\/$/);
});

test("a permalink goes straight to its run: the home overview never loads in between", async ({ page }) => {
  const home: string[] = [];
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname;
    if (p === "/api/overview" || p === "/api/data-health") home.push(p);
  });
  await open(page, "/?run=fx-recon-0001");
  await expect(page.getByTestId("headline")).toHaveText(fixture("reconcile").headline);
  await expect(page.getByTestId("overview")).toHaveCount(0);
  expect(home).toEqual([]);
});

test("a permalink to another persona's run shows nothing of it", async ({ page }) => {
  await open(page, "/?run=fx-refused-0001"); // rm_south's run, opened as head
  await expect(page.getByTestId("error-card")).toContainText("not found for this persona");
  await expect(page.getByTestId("headline")).toHaveCount(0);
  await expect(page.getByTestId("question")).toHaveValue("");
});

test("switching persona refetches Recent", async ({ page }) => {
  await open(page);
  await expect(recent(page)).toHaveCount(HEAD_RUNS.length);
  await page.getByTestId("persona").click();
  await page.getByRole("option", { name: "Regional manager, South" }).click();
  await expect(recent(page)).toHaveCount(1);
  await expect(recent(page)).toHaveAttribute("data-run-id", "fx-refused-0001");
});

test("Recent refetches after each finished ask", async ({ page }) => {
  let fetched = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/history") fetched++;
  });
  await open(page);
  await expect(recent(page)).toHaveCount(HEAD_RUNS.length);
  await expect.poll(() => fetched).toBe(1);
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect.poll(() => fetched).toBe(2);
  // a second ask after a finished one: one more fetch when it finishes, none when it starts
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect.poll(() => fetched).toBe(3);
  await page.waitForTimeout(500);
  expect(fetched).toBe(3);
});

test("thumbs: aria-pressed, Thanks, and the other thumb undoes", async ({ page }) => {
  const posted: unknown[] = [];
  page.on("request", (r) => {
    if (/\/api\/runs\/[^/]+\/feedback$/.test(new URL(r.url()).pathname)) posted.push(r.postDataJSON());
  });
  await open(page, "/?run=fx-explain-0001");
  const up = page.getByTestId("feedback-up");
  const down = page.getByTestId("feedback-down");
  await expect(up).toHaveAttribute("aria-pressed", "false");
  await expect(up).toHaveAccessibleName("Helpful");
  await up.click();
  await expect(up).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("feedback-note")).toHaveText("Thanks");
  await down.click();
  await expect(down).toHaveAttribute("aria-pressed", "true");
  await expect(up).toHaveAttribute("aria-pressed", "false");
  expect(posted).toEqual([
    { persona: "head", rating: 1 },
    { persona: "head", rating: -1 },
  ]);
});

test("a failed rating is not shown as pressed", async ({ page }) => {
  await page.route("**/api/runs/*/feedback", (r) => r.fulfill({ status: 500, body: "boom" }));
  await open(page, "/?run=fx-explain-0001");
  await page.getByTestId("feedback-up").click();
  await expect(page.getByTestId("feedback-note")).toHaveText("Feedback was not saved");
  await expect(page.getByTestId("feedback-up")).toHaveAttribute("aria-pressed", "false");
});

test("Copy link copies the run's permalink", async ({ page, context, baseURL }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();
  await page.getByTestId("copy-link").click();
  await expect(page.getByTestId("copy-link")).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${baseURL}/?run=fx-explain-0001`);
});
