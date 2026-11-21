import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

type Held = { releaseResult(): void };

test("the numbers show before the written answer, then the headline swaps in", async ({ page }) => {
  // Fixture mode streams `partial` then `result` at once: hold the result until the test has looked at the partial.
  await page.addInitScript(() => {
    const real = window.fetch;
    let release = () => {};
    const released = new Promise<void>((r) => (release = r));
    (window as unknown as Held).releaseResult = () => release();
    window.fetch = async (input, init) => {
      if (String(input) !== "/api/ask") return real(input, init);
      const text = await (await real(input, init)).text();
      const cut = text.indexOf("event: result");
      const enc = new TextEncoder();
      const body = new ReadableStream({
        async start(c) {
          c.enqueue(enc.encode(text.slice(0, cut)));
          await released;
          c.enqueue(enc.encode(text.slice(cut)));
          c.close();
        },
      });
      return new Response(body, { headers: { "content-type": "text/event-stream" } });
    };
  });
  await page.goto("/");
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
  await page.getByTestId("question").fill("Why did success rate drop last week?");
  await page.getByTestId("ask-button").click();

  // The partial: the real chart, DQ banners, segment tables and rail evidence; a skeleton where the summary goes.
  await expect(page.getByTestId("summary-skeleton")).toContainText("Writing the summary…");
  const chart = page.getByTestId("key-chart").locator("svg.marks");
  await expect(chart).toBeVisible();
  await expect(page.getByTestId("dq-banner")).toHaveCount(fixture("explain_change").dq.length);
  await expect(page.getByTestId("drivers")).toBeVisible();
  await expect(page.getByTestId("rail").getByRole("tab", { name: "Evidence (3)" })).toBeVisible();
  await expect(page.getByTestId("trace")).toHaveAttribute("aria-busy", "true");
  await expect(page.getByTestId("headline")).toHaveCount(0);
  await expect(page.getByTestId("claim")).toHaveCount(0);
  await expect(page.getByTestId("download-bundle")).toHaveCount(0); // a partial bundle is not the run's record
  await chart.evaluate((el) => el.setAttribute("data-drawn", "partial"));
  // what sits above the summary keeps its size at the swap: the trace is folded already, the footprint keeps its
  // items, and the action buttons' and confidence reasons' rows are held
  const box = (testId: string) =>
    page.getByTestId(testId).evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { top: Math.round(r.top), height: Math.round(r.height) };
    });
  const answerTop = () => page.locator("article").evaluate((el) => Math.round(el.getBoundingClientRect().top));
  const before = { trace: await box("trace"), footprint: (await box("footprint-line")).height, answer: await answerTop() };

  await page.evaluate(() => (window as unknown as Held).releaseResult());
  await expect(page.getByTestId("headline")).toHaveText(fixture("explain_change").headline);
  await expect(page.getByTestId("summary-skeleton")).toHaveCount(0);
  await expect(page.getByTestId("claim")).toHaveCount(fixture("explain_change").claims.length);
  // the swap kept the chart drawn from the partial: no blank, no re-embed
  await expect(page.getByTestId("key-chart").locator('svg.marks[data-drawn="partial"]')).toBeVisible();
  await expect(page.getByTestId("trace")).not.toHaveAttribute("aria-busy", "true");
  expect(await box("trace")).toEqual(before.trace);
  expect((await box("footprint-line")).height).toBe(before.footprint);
  expect(await answerTop()).toBe(before.answer);
});
