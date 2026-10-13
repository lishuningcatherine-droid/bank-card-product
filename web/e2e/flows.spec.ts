import { expect, test } from "@playwright/test";

import { expectAccessible } from "./helpers";

test.describe("critical flows (Example Bank test data)", () => {
  test("credit card: home → quiz → results → detail → compare", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("note")).toContainText("fictional");
    await page.getByRole("link", { name: "Get recommendations" }).first().click();
    await page.getByRole("main").getByRole("link", { name: /^Credit card(?!s)/ }).click();
    await expect(page).toHaveURL(/recommend\/credit-card/);
    await page.getByLabel("Everything else").fill("2000");
    await page.getByRole("button", { name: "See my recommendations" }).click();
    await expect(page).toHaveURL(/recommend\/results#/);
    const results = page.getByRole("list", { name: "Ranked results" });
    await expect(results.getByRole("article").first()).toBeVisible();
    const first = results.getByRole("article").first();
    await expect(first.locator("dt", { hasText: "Ongoing annual value" })).toBeVisible();
    await expect(first.locator("dt", { hasText: "First-year value" })).toBeVisible();
    await expect(first.getByText("Why this matches you")).toBeVisible();
    await expect(page.getByText(/Possible welcome offer: up to/).first()).toBeVisible();
    await expect(page.getByText("Not financial advice.").first()).toBeVisible();
    // adjustable point valuation re-ranks without losing inputs
    await page.getByLabel(/Value of a point or mile/).fill("1.5");
    await page.getByLabel(/Value of a point or mile/).blur();
    await expect(results.getByRole("article").first()).toBeVisible();
    await expectAccessible(page);
    const name = await first.getByRole("heading", { level: 2 }).innerText();
    await first.getByRole("heading", { level: 2 }).getByRole("link").click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    await expect(page.getByRole("heading", { name: "Change history" })).toBeVisible();
    const official = page.getByRole("link", { name: /Official page/ }).first();
    await expect(official).toHaveAttribute("target", "_blank");
    await expect(official).toHaveAttribute("rel", "noopener noreferrer");
    await expect(page.getByText(/Checked/).first()).toBeVisible();
    await page.goto("/credit-cards");
    await page.getByRole("checkbox", { name: /Compare Example Bank Everyday Cash Card/ }).check();
    await page.getByRole("checkbox", { name: /Compare Example Bank Voyager Rewards Card/ }).check();
    await page.getByRole("link", { name: "Compare 2" }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("rowheader", { name: "Annual fee", exact: true })).toBeVisible();
    await expectAccessible(page);
  });

  test("checking: achievability test is shown", async ({ page }) => {
    await page.goto("/recommend/checking");
    await page.getByLabel("Approximate monthly direct deposit").fill("2500");
    await page.getByLabel("State").selectOption("NY");
    await page.getByRole("button", { name: "See my recommendations" }).click();
    const card = page.getByRole("article").filter({ hasText: "Example Bank Everyday Checking" });
    await expect(card.getByText("Requirement achievable: yes")).toBeVisible();
    await expect(card.getByText(/\$2,500\/month × 3 months/)).toBeVisible();
    await card.getByRole("link", { name: "Example Bank Everyday Checking", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Example Bank Everyday Checking");
    await page.goto("/checking-accounts");
    await page.getByRole("checkbox", { name: /Compare Example Bank Everyday Checking/ }).check();
    await page.getByRole("checkbox", { name: /Compare Example Bank Online Checking/ }).check();
    await page.getByRole("link", { name: "Compare 2" }).click();
    await expect(page.getByRole("rowheader", { name: "Monthly fee" })).toBeVisible();
  });

  test("savings: deposit and holding-period rules", async ({ page }) => {
    await page.goto("/recommend/savings");
    await page.getByLabel("$1,000–$5,000").check();
    await page.getByRole("button", { name: "See my recommendations" }).click();
    const hy = page.getByRole("article").filter({ hasText: "Example Bank High Yield Savings" });
    await expect(hy.getByText(/Bonus not counted: your deposit/)).toBeVisible();
    await page.goto("/recommend/savings");
    await page.getByLabel("$25,000–$100,000").check();
    await page.getByRole("button", { name: "See my recommendations" }).click();
    await expect(page.getByRole("article").filter({ hasText: "Example Bank High Yield Savings" }).getByText(/Bonus counted/)).toBeVisible();
    await page.getByRole("link", { name: "Example Bank Tiered Savings", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Example Bank Tiered Savings");
    await page.goto("/savings-accounts");
    await page.getByRole("checkbox", { name: /Compare Example Bank High Yield Savings/ }).check();
    await page.getByRole("checkbox", { name: /Compare Example Bank Tiered Savings/ }).check();
    await page.getByRole("link", { name: "Compare 2" }).click();
    await expect(page.getByRole("rowheader", { name: "APY", exact: true })).toBeVisible();
  });
});

test.describe("filters, empty and error states", () => {
  test("listing filters", async ({ page }) => {
    await page.goto("/credit-cards");
    await expect(page.getByText("7 products")).toBeVisible();
    await page.getByRole("checkbox", { name: "Secured", exact: true }).check();
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect(page.getByText("1 product")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Example Bank Secured Card" })).toBeVisible();
    await page.goto("/credit-cards?q=zzzz");
    await expect(page.getByRole("heading", { name: "No products match these filters" })).toBeVisible();
    await page.goto("/savings-accounts?apy_min=4");
    await expect(page.getByText("1 product")).toBeVisible();
    await page.goto("/credit-cards?annual_fee_max=0&segment=business");
    await expect(page.getByRole("heading", { name: "Example Bank Business Cash Card" })).toBeVisible();
  });

  test("results empty state", async ({ page }) => {
    await page.goto("/recommend/credit-card");
    await page.getByLabel("Business", { exact: true }).check();
    await page.getByLabel("Secured card").check();
    await page.getByRole("button", { name: "See my recommendations" }).click();
    await expect(page.getByRole("heading", { name: "No verified products match your answers" })).toBeVisible();
  });

  test("results error state with retry", async ({ page }) => {
    let fail = true;
    await page.route("**/api/v1/recommend", (route) => (fail ? route.fulfill({ status: 500, body: "{}" }) : route.continue()));
    await page.goto("/recommend/savings");
    await page.getByRole("button", { name: "See my recommendations" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Something went wrong" })).toContainText("We couldn't calculate recommendations.");
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("list", { name: "Ranked results" })).toBeVisible();
  });

  test("results without answers and unknown product", async ({ page }) => {
    await page.goto("/recommend/results");
    await expect(page.getByRole("heading", { name: "No answers yet" })).toBeVisible();
    const res = await page.goto("/products/00000000-0000-0000-0000-000000000000");
    expect(res?.status()).toBe(404);
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });

  test("inputs never reach the web server", async ({ page }) => {
    const seen: string[] = [];
    page.on("request", (r) => seen.push(r.url()));
    await page.goto("/recommend/checking");
    await page.getByLabel("Approximate monthly direct deposit").fill("7373");
    await page.getByRole("button", { name: "See my recommendations" }).click();
    await expect(page.getByRole("list", { name: "Ranked results" })).toBeVisible();
    expect(seen.filter((u) => u.startsWith("http://127.0.0.1:3010")).some((u) => u.includes("7373"))).toBe(false);
  });
});
