import { expect, test, type Page } from "@playwright/test";

const brand = (page: Page) => page.locator("[data-slot=sidebar-header]").getByText("Sherpa", { exact: true });

test("every route renders the shell", async ({ page }) => {
  for (const [path, heading] of [["/", "Ask"], ["/explore", "Explore"], ["/eval", "Eval"], ["/runs", "Runs"]]) {
    await page.goto(path);
    await expect(brand(page)).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
});

test("persona select lists both personas", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
  await page.getByTestId("persona").click();
  await expect(page.getByRole("option")).toHaveText(["Business head (all regions)", "Regional manager, South"]);
});

test("theme toggle switches the html class", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const html = page.locator("html");
  const toggle = page.getByTestId("theme-toggle");
  await expect(html).not.toHaveClass(/\bdark\b/);
  await expect(toggle).toHaveAccessibleName("Theme: system");
  await toggle.click(); // system -> light
  await expect(toggle).toHaveAccessibleName("Theme: light");
  await expect(html).not.toHaveClass(/\bdark\b/);
  await toggle.click(); // light -> dark
  await expect(html).toHaveClass(/\bdark\b/);
  await page.reload(); // the head script restores it before paint
  await expect(html).toHaveClass(/\bdark\b/);
  await page.getByTestId("theme-toggle").click(); // dark -> system (light here)
  await expect(html).not.toHaveClass(/\bdark\b/);
});

test("works without localStorage", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => {
    const blocked = () => {
      throw new DOMException("storage is blocked", "SecurityError");
    };
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: { getItem: blocked, setItem: blocked, removeItem: blocked, clear: blocked, key: blocked, length: 0 },
    });
  });
  await page.goto("/");
  await expect(brand(page)).toBeVisible();
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
  await page.getByTestId("persona").click();
  await page.getByRole("option", { name: "Regional manager, South" }).click();
  await expect(page.getByTestId("persona")).toHaveText("Regional manager, South");
  await page.getByTestId("theme-toggle").click();
  await expect(page.getByTestId("theme-toggle")).toHaveAccessibleName("Theme: light");
  expect(errors).toEqual([]);
});

test("rail becomes a sheet below 1280px", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("rail")).toHaveCount(0);
  await page.getByRole("button", { name: "Inspector" }).click();
  await expect(page.getByTestId("rail-sheet")).toBeVisible();

  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("rail")).toBeVisible();
  await expect(page.getByRole("button", { name: "Inspector" })).toHaveCount(0);
});
