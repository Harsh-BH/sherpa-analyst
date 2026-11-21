import { expect, test } from "@playwright/test";

test("explore builds a catalog plan and runs it", async ({ page }) => {
  await page.goto("/explore");
  await expect(page.getByTestId("persona")).toBeVisible();
  await page.getByTestId("dim-payment_method").click();
  await page.getByTestId("filter-dim-region").click();
  await page.getByTestId("filter-val-region-South").click();
  const json = page.getByTestId("plan-json");
  await expect(json).toContainText('"route": "catalog"');
  await expect(json).toContainText('"payment_method"');
  await expect(json).toContainText('"South"');
  await expect(page.getByText("Question:").first()).toBeVisible();
  await page.getByRole("button", { name: "Run plan" }).click();
  await expect(page.getByTestId("headline")).toBeVisible();
});

test("explore disables Run plan while a changed form's plan is in flight", async ({ page }) => {
  await page.route("**/api/explore/plan", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto("/explore");
  const run = page.getByRole("button", { name: "Run plan" });
  await expect(run).toBeEnabled({ timeout: 10_000 });
  await page.getByTestId("dim-payment_method").click();
  await expect(run).toBeDisabled();
  await expect(run).toBeEnabled({ timeout: 10_000 });
});
