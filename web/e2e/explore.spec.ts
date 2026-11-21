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
