import { expect, test } from "@playwright/test";

import { expectAccessible, expectNoHorizontalScroll } from "./helpers";

const PAGES = ["/", "/credit-cards", "/checking-accounts", "/savings-accounts", "/recommend", "/recommend/credit-card",
  "/recommend/checking", "/recommend/savings", "/methodology", "/sources", "/about", "/privacy", "/disclaimer",
  "/compare", "/does-not-exist"];

for (const path of PAGES) {
  test(`axe: ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await expectAccessible(page);
  });
}

test("axe: product detail", async ({ page }) => {
  await page.goto("/credit-cards?q=voyager");
  await page.getByRole("link", { name: "Example Bank Voyager Rewards Card", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Change history" })).toBeVisible();
  // up-to offer wording with an accessible toggletip
  await expect(page.getByText("Up to", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "About this offer amount" }).first().click();
  await expect(page.getByRole("tooltip")).toContainText("may be lower than this maximum");
  await expectAccessible(page);
});

for (const width of [375, 768, 1280]) {
  test(`responsive ${width}px has no horizontal page scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/credit-cards", "/recommend/credit-card", "/methodology", "/sources"]) {
      await page.goto(path);
      await expectNoHorizontalScroll(page);
    }
  });
}

test("keyboard: skip link and visible focus", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  const outline = await skip.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
});
