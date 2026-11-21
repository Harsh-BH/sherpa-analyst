import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../tests/fixtures", `${name}.json`), "utf8"));

async function ready(page: Page, url: string) {
  await page.goto(url);
  await expect(page.getByTestId("persona")).toBeVisible();
}

test("clarification options show previews and answer", async ({ page }) => {
  await ready(page, "/?q=" + encodeURIComponent("What was the success rate yesterday?"));
  const options = page.getByTestId("clarify-option");
  await expect(options).toHaveCount(2);
  for (const o of await options.all()) await expect(o).toContainText("%");
  await options.first().click();
  await expect(page.getByTestId("headline")).toBeVisible();
});

test("refusal card and suggested plan", async ({ page }) => {
  await ready(page, "/?persona=rm_south&q=" + encodeURIComponent("Compare North vs South success rate"));
  await expect(page.getByText("Not answered")).toBeVisible();
  await expect(page.getByText("out of scope")).toBeVisible();
  await expect(page.getByText("persona rm_south")).toBeVisible();
  await page.getByTestId("refusal-accept").click();
  await expect(page.getByTestId("headline")).toBeVisible();
});

test("error card keeps run id", async ({ page }) => {
  await ready(page, "/?q=x&fixture=error");
  const card = page.getByTestId("error-card");
  await expect(card).toContainText("This run failed");
  await expect(card).toContainText(fixture("error").run_id);
  await expect(card.locator("code")).toHaveText("fx-error-0001");
  await expect(card.getByRole("button", { name: "Copy run id" })).toBeVisible();
});

test("partial bundle renders", async ({ page }) => {
  const errors: Error[] = [];
  page.on("pageerror", (e) => errors.push(e));
  await ready(page, "/?q=x&fixture=partial");
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.getByText("E9 · not in this bundle").first()).toBeVisible();
  expect(errors).toEqual([]);
});
