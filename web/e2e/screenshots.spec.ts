import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

/** Captures every major page at 375px and 1280px into docs/screenshots (run with SCREENSHOTS=1). Test data only. */
const OUT = join(process.cwd(), "..", "docs", "screenshots");
const WIDTHS = [375, 1280];

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture docs/screenshots");

async function shot(page: import("@playwright/test").Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: join(OUT, `${name}-${width}.png`), fullPage: true });
  }
}

test("capture", async ({ page }) => {
  test.setTimeout(180_000);
  mkdirSync(OUT, { recursive: true });
  for (const [path, name] of [["/", "home"], ["/credit-cards", "credit-cards"], ["/checking-accounts", "checking-accounts"],
    ["/savings-accounts", "savings-accounts"], ["/recommend", "recommend-start"], ["/recommend/credit-card", "quiz-credit-card"],
    ["/methodology", "methodology"], ["/sources", "sources"], ["/about", "about"], ["/privacy", "privacy"],
    ["/credit-cards?q=zzzz", "empty-state"], ["/does-not-exist", "not-found"]] as const) {
    await page.goto(path);
    await shot(page, name);
  }
  await page.goto("/credit-cards?q=voyager");
  await page.getByRole("link", { name: "Example Bank Voyager Rewards Card", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Change history" })).toBeVisible();
  await shot(page, "product-detail");
  for (const [type, name] of [["credit-card", "results-credit-card"], ["checking", "results-checking"], ["savings", "results-savings"]] as const) {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/recommend/${type}`);
    if (type === "checking") await page.getByLabel("Approximate monthly direct deposit").fill("2500");
    await page.getByRole("button", { name: "See my recommendations" }).click();
    // card results are grouped (cash back / points and miles); deposit results are one list
    await expect(page.getByRole("list", { name: /^(Ranked results|Cash back cards)$/ })).toBeVisible();
    await shot(page, name);
  }
  await page.goto("/credit-cards");
  await page.getByRole("checkbox", { name: /Compare Example Bank Everyday Cash Card/ }).check();
  await page.getByRole("checkbox", { name: /Compare Example Bank Voyager Rewards Card/ }).check();
  await page.getByRole("checkbox", { name: /Compare Example Air Miles Card/ }).check();
  await page.getByRole("link", { name: "Compare 3" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await shot(page, "compare");
});
