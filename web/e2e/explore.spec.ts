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

test("explore defaults the baseline to the preceding window of equal length", async ({ page }) => {
  await page.goto("/explore");
  await page.getByRole("combobox", { name: "Intent", exact: true }).click();
  await page.getByRole("option", { name: "Explain change", exact: true }).click();
  await page.getByRole("combobox", { name: "Window", exact: true }).click();
  await page.getByRole("option", { name: "last 30 days", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Baseline", exact: true })).toHaveText("preceding window of equal length");
  // baseline null: the pipeline compares against the equal-length window before (a preset would overlap last 30 days)
  const json = page.getByTestId("plan-json");
  await expect
    .poll(async () => {
      const p = JSON.parse((await json.textContent()) ?? "{}");
      return [p.intent, p.window?.preset, p.baseline];
    })
    .toEqual(["explain_change", "last_30_days", null]);
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
