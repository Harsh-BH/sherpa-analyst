import { expect, test, type Page } from "@playwright/test";

async function open(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.getByTestId("persona")).toHaveText("Business head (all regions)");
}

const palette = (page: Page) => page.getByTestId("palette");
const filter = (page: Page) => page.getByTestId("palette-input");
const options = (page: Page) => page.getByTestId("palette-option");

test("⌘K opens the palette, the filter narrows it and Enter navigates", async ({ page }) => {
  await open(page);
  await page.keyboard.press("ControlOrMeta+k");
  await expect(palette(page)).toBeVisible();
  await expect(filter(page)).toBeFocused();
  for (const group of ["Pages", "Questions", "Personas", "Help"])
    await expect(palette(page).getByRole("group", { name: group })).toBeVisible();

  await filter(page).fill("eval");
  await expect(options(page).first()).toHaveText("Eval");
  await expect(options(page).first()).toHaveAttribute("data-group", "Pages");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/eval$/);
  await expect(palette(page)).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "Eval" })).toBeVisible();
});

test("arrows move the active option through aria-activedescendant; Esc closes", async ({ page }) => {
  await open(page);
  await page.keyboard.press("ControlOrMeta+k");
  const active = async (i: number) => {
    const option = i < 0 ? options(page).last() : options(page).nth(i);
    await expect(option).toHaveAttribute("aria-selected", "true");
    await expect(filter(page)).toHaveAttribute("aria-activedescendant", (await option.getAttribute("id"))!);
  };
  await expect(filter(page)).toHaveAttribute("role", "combobox");
  await active(0);
  await page.keyboard.press("ArrowDown");
  await active(1);
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp"); // wraps round to the last option
  await active(-1);
  await expect(page.getByRole("option", { selected: true })).toHaveCount(1);

  await filter(page).fill("zzzz no such command");
  await expect(options(page)).toHaveCount(0);
  await expect(palette(page).getByRole("status")).toHaveText("No matches");

  await page.keyboard.press("Escape");
  await expect(palette(page)).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+k"); // opens fresh: the filter is empty again
  await expect(filter(page)).toHaveValue("");
  await page.keyboard.press("ControlOrMeta+k"); // and the shortcut toggles it shut
  await expect(palette(page)).toHaveCount(0);
});

test("a question from the palette is asked on the Ask page", async ({ page }) => {
  await open(page, "/runs");
  await page.keyboard.press("ControlOrMeta+k");
  await filter(page).fill("questions");
  const question = (await options(page).first().textContent())!;
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("question")).toHaveValue(question);
  await expect(page.getByTestId("trace")).toBeVisible();
});

test("the Recent group lists the persona's runs from the history, and Enter reopens one", async ({ page }) => {
  await open(page, "/eval");
  await expect(page.getByTestId("recent").getByTestId("recent-run")).toHaveCount(5); // fixture history has loaded
  await page.keyboard.press("ControlOrMeta+k");
  const recent = palette(page).getByRole("group", { name: "Recent" });
  await expect(recent.getByTestId("palette-option")).toHaveCount(5);
  await filter(page).fill("recent");
  await expect(options(page).first()).toHaveAttribute("data-group", "Recent");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/\?run=fx-recon-0001$/);
  await expect(page.getByTestId("headline")).toBeVisible();
});

test("switching persona from the palette", async ({ page }) => {
  await open(page);
  await page.keyboard.press("ControlOrMeta+k");
  await filter(page).fill("switch south");
  await expect(options(page)).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("persona")).toHaveText("Regional manager, South");
  await page.keyboard.press("ControlOrMeta+k");
  await filter(page).fill("switch");
  await expect(options(page).filter({ hasText: "Regional manager, South" })).toContainText("current");
});

test("keyboard shortcuts are listed in the palette", async ({ page }) => {
  await open(page);
  await page.keyboard.press("ControlOrMeta+k");
  await filter(page).fill("shortcuts");
  await page.keyboard.press("Enter");
  const list = page.getByTestId("shortcuts");
  await expect(list).toContainText(/(⌘|Ctrl) K/);
  await expect(list).toContainText("Focus the question box");
  await list.getByRole("button", { name: "Back to commands" }).click();
  await expect(filter(page)).toBeVisible();
});

test("the sidebar hint names the shortcut and opens the palette", async ({ page }) => {
  await open(page);
  const hint = page.getByTestId("palette-hint");
  await expect(hint).toHaveText(/Search\s*(⌘K|Ctrl K)/);
  await expect(hint).toHaveAttribute("aria-keyshortcuts", /^(Meta|Control)\+K$/);
  await hint.click();
  await expect(palette(page)).toBeVisible();
});

test('"/" focuses the question box, and types a slash inside a field', async ({ page }) => {
  await open(page);
  await page.keyboard.press("/");
  const box = page.getByTestId("question");
  await expect(box).toBeFocused();
  await expect(box).toHaveValue("");
  await page.keyboard.type("a/b");
  await expect(box).toHaveValue("a/b");
});
