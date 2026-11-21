import { expect, test, type Page } from "@playwright/test";

const EXPLAIN = "Why did success rate drop last week?";

async function answer(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
  await page.getByTestId("question").fill(EXPLAIN);
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("headline")).toBeVisible();
}

/** The first claim's entry animation (globals.css `rise`), as computed. */
const claimAnimation = (page: Page) =>
  page
    .getByTestId("claim")
    .first()
    .evaluate((el) => {
      const s = getComputedStyle(el);
      return { name: s.animationName, seconds: parseFloat(s.animationDuration) };
    });

test("claims rise in", async ({ page }) => {
  await answer(page);
  expect(await claimAnimation(page)).toEqual({ name: "rise", seconds: 0.32 });
});

test("reduced motion makes the entry animation instant", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await answer(page);
  const a = await claimAnimation(page);
  expect(a.name === "none" || a.seconds <= 0.01, JSON.stringify(a)).toBe(true);
});

test("a question in flight shows the progress bar and a pulsing stage", async ({ page }) => {
  // An /api/ask stream that sends one stage and never ends, so the run stays in flight.
  await page.addInitScript(() => {
    const real = window.fetch;
    window.fetch = (input, init) => {
      if (String(input) !== "/api/ask") return real(input, init);
      const sse = 'event: stage\ndata: {"name":"plan","t_ms":12,"elapsed":"12 ms"}\n\n';
      const body = new ReadableStream({ start: (c) => c.enqueue(new TextEncoder().encode(sse)) });
      return Promise.resolve(new Response(body, { headers: { "content-type": "text/event-stream" } }));
    };
  });
  await page.goto("/");
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
  await page.getByTestId("question").fill(EXPLAIN);
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("run-progress")).toBeVisible();
  await expect(page.getByTestId("trace").getByTestId("stage-pulse")).toHaveCount(1);
});
