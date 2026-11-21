import { expect, test } from "@playwright/test";

test("eval shows 7 tiles and the cases table", async ({ page }) => {
  await page.goto("/eval");
  await expect(page.getByTestId("eval-tile")).toHaveCount(7);
  await expect(page.getByTestId("eval-tile").first()).toContainText("baseline");
  await expect(page.getByText("Generated").first()).toContainText(/^Generated .+ · data .+/);
  await expect(page.getByTestId("eval-cases")).toBeVisible();
  await expect(page.getByTestId("eval-cases").getByText(/^(Pass|Fail)$/).first()).toBeVisible();
});

test("eval case opens in the rail", async ({ page }) => {
  await page.goto("/eval");
  await page.getByTestId("eval-cases").getByRole("row").nth(1).click();
  await expect(page.getByTestId("rail").getByTestId("eval-case-detail")).toBeVisible();
});

test("runs shows tiles or a clear unavailable message", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.getByTestId("run-tile").first().or(page.getByTestId("runs-unavailable"))).toBeVisible();
  if (await page.getByTestId("runs-unavailable").isVisible()) return;
  await expect(page.getByTestId("run-tile")).toHaveCount(7);
  const rows = page.getByTestId("runs-table").getByRole("row");
  if ((await rows.count()) > 1) {
    await rows.nth(1).click();
    await expect(page.getByTestId("rail").getByTestId("run-footprint")).toBeVisible();
  }
});
