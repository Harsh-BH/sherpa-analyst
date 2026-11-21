import { expect, test, type Locator, type Page } from "@playwright/test";

const PHONE = { width: 390, height: 844 };
const EXPLAIN = "Why did success rate drop last week?";

// Reduced motion: sheets land at once, so their boxes can be measured.
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize(PHONE);
});

/** What scrolls sideways: the page itself, or a pane that should only scroll down (tables scroll in their own box). */
const sideways = (page: Page) =>
  page.evaluate(() => {
    const bad = [...document.querySelectorAll<HTMLElement>(".overflow-y-auto")]
      .filter((e) => e.scrollWidth > e.clientWidth)
      .map((e) => e.className);
    if (document.documentElement.scrollWidth > window.innerWidth) bad.push("html");
    return bad;
  });

async function atLeast40(target: Locator) {
  const box = (await target.boundingBox())!;
  expect(box.height, await target.evaluate((e) => e.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(40);
  expect(box.width).toBeGreaterThanOrEqual(40);
}

test("no horizontal page scroll on /, /eval and /runs at 390 and 768 px", async ({ page }) => {
  const pages: [string, (p: Page) => Locator][] = [
    ["/", (p) => p.getByTestId("kpi-card").first()],
    ["/eval", (p) => p.getByTestId("eval-cases")],
    ["/runs", (p) => p.getByTestId("run-tile").first().or(p.getByTestId("runs-unavailable"))],
  ];
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    for (const [path, ready] of pages) {
      await page.goto(path);
      await expect(ready(page)).toBeVisible();
      expect(await sideways(page), `${path} at ${width} px`).toEqual([]);
    }
  }
});

/** Open Ask and wait for the overview (meta and the persona have loaded), so typing lands after hydration. */
async function home(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("kpi-card").first()).toBeVisible();
}

test("phone: an answer fits the width too", async ({ page }) => {
  await home(page);
  await page.getByTestId("question").fill(EXPLAIN);
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("key-chart").locator("svg.marks")).toBeVisible();
  expect(await sideways(page)).toEqual([]);
});

test("phone: compact top bar, off-canvas sidebar, 40 px tap targets", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("kpi-card").first()).toBeVisible();
  const menu = page.getByRole("button", { name: "Open menu" });
  for (const target of [
    menu,
    page.getByRole("button", { name: "Open command palette" }),
    page.getByRole("button", { name: "Inspector" }),
    page.getByTestId("question"),
    page.getByTestId("ask-button"),
    page.getByTestId("demo-chip").first(),
  ])
    await atLeast40(target);

  // The sidebar is off-canvas until the menu button opens it; following a link closes it again.
  await expect(page.getByTestId("persona")).toBeHidden();
  await menu.click();
  await expect(page.getByTestId("persona")).toBeVisible();
  await atLeast40(page.getByRole("link", { name: "Runs" }));
  await page.getByRole("link", { name: "Runs" }).click();
  await expect(page).toHaveURL(/\/runs$/);
  await expect(page.getByTestId("persona")).toBeHidden();
});

test("phone: KPI cards in 2 columns and a sticky question bar", async ({ page }) => {
  await page.goto("/");
  const cards = page.getByTestId("kpi-card");
  await expect(cards).toHaveCount(4);
  const tops = await cards.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  expect(tops[0]).toBe(tops[1]);
  expect(tops[2]).toBeGreaterThan(tops[0]);

  const box = page.getByTestId("question");
  const before = (await box.boundingBox())!.y;
  await box.evaluate((e) => e.closest(".overflow-y-auto")!.scrollTo(0, 600));
  expect((await box.boundingBox())!.y).toBe(before);
});

test("phone: an eval row opens the rail as a bottom sheet", async ({ page }) => {
  await page.goto("/eval");
  await page.getByTestId("eval-cases").getByRole("row").nth(1).click();
  const sheet = page.getByTestId("rail-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet).toHaveAttribute("data-side", "bottom");
  await expect(sheet.getByTestId("eval-case-detail")).toBeVisible();
  const box = (await sheet.boundingBox())!;
  expect(box.height).toBeLessThanOrEqual(PHONE.height * 0.85 + 1);
  expect(Math.abs(box.y + box.height - PHONE.height)).toBeLessThanOrEqual(1);
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
});

test("phone: a runs row opens the rail sheet", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.getByTestId("run-tile").first().or(page.getByTestId("runs-unavailable"))).toBeVisible();
  const rows = page.getByTestId("runs-table").getByRole("row");
  test.skip((await rows.count()) < 2, "no runs recorded");
  await rows.nth(1).click();
  const sheet = page.getByTestId("rail-sheet");
  await expect(sheet.getByTestId("run-footprint")).toBeVisible();
  await sheet.getByRole("button", { name: "Close" }).click();
  await expect(sheet).toHaveCount(0);
});

test("phone: an evidence chip opens the bottom sheet at its entry", async ({ page }) => {
  await home(page);
  await page.getByTestId("question").fill(EXPLAIN);
  await page.getByTestId("ask-button").click();
  await page.getByTestId("chip-E2").first().click();
  const sheet = page.getByTestId("rail-sheet");
  await expect(sheet).toHaveAttribute("data-side", "bottom");
  await expect(sheet.getByTestId("evidence-E2")).toHaveAttribute("data-selected", "true");
});

test("phone: the top bar opens the command palette", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open command palette" }).click();
  await expect(page.getByTestId("palette")).toBeVisible();
  const box = (await page.getByTestId("palette").boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width);
});
