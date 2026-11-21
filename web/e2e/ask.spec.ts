import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

const EXPLAIN = "Why did success rate drop last week?";
const SQL_Q = "Which merchants had the most failed payments last week?";
const HEAD = "Business head (all regions)";

/** Open Ask and wait until meta has loaded (the persona shows), so the page is hydrated. */
async function open(page: Page, url = "/") {
  await page.goto(url);
  await expect(page.getByTestId("persona")).toHaveText(HEAD);
}

async function ask(page: Page, question: string) {
  await page.getByTestId("question").fill(question);
  await page.getByTestId("ask-button").click();
}

const askRequests = (page: Page) => {
  const bodies: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/ask") bodies.push(r.postData() ?? "");
  });
  return bodies;
};

test("explain_change shows tags, DQ before headline, footprint", async ({ page }) => {
  await open(page);
  await ask(page, EXPLAIN);
  const headline = page.getByTestId("headline");
  await expect(headline).toHaveText(fixture("explain_change").headline);

  const claims = page.getByTestId("claim");
  const kinds = await claims.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")));
  expect(new Set(kinds)).toEqual(new Set(["fact", "hypothesis", "recommendation", "caveat"]));
  for (const tag of ["Fact", "Hypothesis", "Recommendation", "Caveat"])
    await expect(claims.getByText(tag, { exact: true }).first()).toBeVisible();
  await expect(claims.first()).toHaveAttribute("data-cites", "E1");

  const banners = page.getByTestId("dq-banner");
  await expect(banners).not.toHaveCount(0);
  const top = (await headline.boundingBox())!.y;
  for (const b of await banners.all()) expect((await b.boundingBox())!.y).toBeLessThan(top);

  await expect(page.getByTestId("footprint-line")).toContainText("run");
  await expect(page.getByTestId("trace")).toContainText("2 steps"); // collapsed to view.footprint.summary
  const footer = page.locator("[data-slot=sidebar-footer]");
  await expect(footer).toContainText("v1 · seed 42");
  await expect(footer).toContainText("19 Nov 2026");

  await expect(page.getByTestId("download-bundle")).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-bundle").click()]);
  expect(download.suggestedFilename()).toBe("sherpa-run-fx-explain-0001.json");
  expect(JSON.parse(readFileSync(await download.path(), "utf8")).run_id).toBe("fx-explain-0001");
});

test("sql_route is labelled and injection stays text", async ({ page }) => {
  const injection: string = fixture("sql_route").evidence[0].table[1].display_name;
  const rawImg = injection.match(/<img[^>]*>/)![0];
  await open(page);
  await ask(page, SQL_Q);
  await expect(page.getByTestId("badge-route")).toHaveText("Unverified SQL");
  await expect(page.getByTestId("sql-warning")).toContainText("Unverified SQL");
  const chip = page.getByTestId("chip-E1").first();
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(await page.content()).not.toContain(rawImg);
});

test("demo chip switches persona", async ({ page }) => {
  await open(page);
  await page.getByTestId("demo-chip").filter({ hasText: "Compare North vs South success rate" }).click();
  await expect(page.getByTestId("persona")).toHaveText("Regional manager, South");
  await expect(page.getByText("out of scope", { exact: false })).toBeVisible();
});

test("deep link asks once and ignores unknown persona", async ({ page }) => {
  const asks = askRequests(page);
  await page.goto("/?q=Why%20did%20success%20rate%20drop%20last%20week%3F&persona=superuser");
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.getByTestId("persona")).toHaveText(HEAD);
  expect(asks.map((b) => JSON.parse(b))).toEqual([{ question: EXPLAIN, persona: "head" }]);
});

test("empty question is ignored", async ({ page }) => {
  const asks = askRequests(page);
  await open(page);
  await page.getByTestId("ask-button").click();
  await ask(page, "   ");
  await page.waitForTimeout(300); // a request, if any, would have left by now
  expect(asks).toEqual([]);
  await expect(page.getByTestId("trace")).toHaveCount(0);
});

test("api failure shows an error card", async ({ page }) => {
  await page.route("**/api/ask", (r) => r.abort());
  await open(page);
  await ask(page, EXPLAIN);
  await expect(page.getByTestId("error-card")).toContainText("Sherpa API unreachable");
});

test("meta failure is reported and never asks without a persona", async ({ page }) => {
  const asks = askRequests(page);
  await page.route("**/api/meta", (r) => r.abort());
  await page.goto("/");
  await expect(page.getByTestId("meta-error")).toContainText("Sherpa API unreachable");
  await expect(page.getByTestId("persona")).toHaveText("Personas unavailable");
  await ask(page, EXPLAIN);
  await expect(page.getByTestId("error-card")).toContainText("Sherpa API unreachable");
  expect(asks).toEqual([]);
});

test("question and answer survive crossing 1280 px", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await open(page);
  await ask(page, EXPLAIN);
  await expect(page.getByTestId("headline")).toBeVisible();
  await page.getByTestId("question").fill("half-typed");
  await page.setViewportSize({ width: 1100, height: 900 }); // the centre remounts inside the narrow layout
  await expect(page.getByRole("button", { name: "Inspector" })).toBeVisible();
  await expect(page.getByTestId("question")).toHaveValue("half-typed");
  await expect(page.getByTestId("headline")).toBeVisible();
});

test("trace records when each stage and the result arrive", async ({ page }) => {
  // Fixture mode sends no stages: put two in front of the real result event.
  await page.route("**/api/ask", async (route) => {
    const real = await route.fetch();
    const stages = ["plan", "triage"].map((name, i) => `event: stage\ndata: {"name":"${name}","t_ms":${i}}\n\n`);
    await route.fulfill({ response: real, body: stages.join("") + (await real.text()) });
  });
  await open(page);
  await ask(page, EXPLAIN);
  await expect(page.getByTestId("headline")).toBeVisible();
  const times: [string, number][] = JSON.parse((await page.getByTestId("trace").getAttribute("data-stage-times"))!);
  expect(times.map(([name]) => name)).toEqual(["plan", "triage", "result"]);
  expect(times.every(([, ms]) => Number.isInteger(ms) && ms >= 0)).toBe(true);
});

test("running trace shows each stage with the API's elapsed time", async ({ page }) => {
  // An /api/ask stream that sends two stages and never ends, so the run stays in flight.
  await page.addInitScript(() => {
    const real = window.fetch;
    window.fetch = (input, init) => {
      if (String(input) !== "/api/ask") return real(input, init);
      const sse =
        'event: stage\ndata: {"name":"plan","t_ms":12,"elapsed":"12 ms"}\n\n' +
        'event: stage\ndata: {"name":"triage","t_ms":2340,"elapsed":"2.3 s"}\n\n';
      const body = new ReadableStream({ start: (c) => c.enqueue(new TextEncoder().encode(sse)) });
      return Promise.resolve(new Response(body, { headers: { "content-type": "text/event-stream" } }));
    };
  });
  await open(page);
  await ask(page, EXPLAIN);
  const trace = page.getByTestId("trace");
  await expect(trace).toHaveAttribute("aria-busy", "true");
  await expect(trace.getByRole("listitem")).toHaveText([/^Plan\s*12 ms$/, /^Triage\s*2\.3 s$/]);
});

test("second question wins", async ({ page }) => {
  let n = 0;
  await page.route("**/api/ask", async (route) => {
    if (n++ === 0) await new Promise((r) => setTimeout(r, 1500));
    await route.continue().catch(() => {}); // by then the browser has aborted the first request
  });
  await open(page);
  await ask(page, SQL_Q);
  await ask(page, EXPLAIN);
  await page.waitForTimeout(3000);
  await expect(page.getByTestId("headline")).toHaveText(fixture("explain_change").headline);
  await expect(page.getByTestId("badge-route")).not.toHaveText("Unverified SQL");
});
