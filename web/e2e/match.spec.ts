import { expect, type Page, test } from "@playwright/test";

import { expectAccessible } from "./helpers";

// The personal offer check on fictional Example Bank campaigns (tests/fixtures/tracker/example_cards.yaml).

async function basics(page: Page, a: { history: string; spend: string; opened: string; marks: "yes" | "no" }) {
  await page.getByLabel("How long have you had credit?").selectOption(a.history);
  await page.getByLabel(/Normal monthly card spending/).fill(a.spend);
  await page.getByLabel(/Credit cards opened in the last 24 months/).fill(a.opened);
  await page.getByLabel(/Late payments, collections or bankruptcy/).selectOption(a.marks);
}

const check = (page: Page) => page.getByRole("button", { name: "Check offers for me" }).click();
const article = (page: Page, name: RegExp) => page.getByRole("article").filter({ has: page.getByRole("heading", { name }) });

test.describe("personal offer check (Example Bank test data)", () => {
  test("complete answers: six judgements, approval and bonus apart, an action per offer", async ({ page }) => {
    await page.goto("/offers/match");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Is this offer right for me?");
    await basics(page, { history: "5y_plus", spend: "3000", opened: "1", marks: "no" });
    await check(page);
    await expect(page.getByRole("heading", { name: /^Results/ })).toBeVisible();
    const everyday = article(page, /Example Bank Everyday Cash Card/);
    await expect(everyday.getByText(/Suggested action:/)).toBeVisible();
    for (const region of ["Can you be approved?", "Can you earn this bonus?", "1. Offer appeal", "2. Personal fit", "3. Reaching the spend"]) {
      await expect(everyday.getByRole("region", { name: region })).toBeVisible();
    }
    await expect(everyday.getByText(/does not estimate approval odds/)).toBeVisible();
    await expect(everyday.getByText(/First-year value/)).toBeVisible();
    await expect(page.getByText("You could consider it now").first()).toBeVisible();
    await expect(page.getByText(/Not financial advice/i).first()).toBeVisible();
    await expectAccessible(page);
  });

  test("thin credit file: regular card says improve credit first, the student card does not", async ({ page }) => {
    await page.goto("/offers/match");
    await basics(page, { history: "lt_1y", spend: "600", opened: "0", marks: "no" });
    await check(page);
    const regular = article(page, /Example Bank Everyday Cash Card/);
    await expect(regular.getByText("Suggested action: Improve your credit first")).toBeVisible();
    const student = article(page, /Example Bank Student Cash Card/);
    await expect(student.getByText("Starter card: student")).toBeVisible();
    await expect(student.getByText(/Suggested action: Improve your credit first/)).toHaveCount(0);
    await expect(student.getByText(/does not mean approval is easy/)).toBeVisible();
  });

  test("only a credit score: no firm answer, the next questions are asked", async ({ page }) => {
    await page.goto("/offers/match");
    await page.getByText("More details (improves the check)").click();
    await page.getByLabel(/Credit score \(optional\)/).fill("720");
    await check(page);
    await expect(page.getByText("Answer these next for a firmer result:")).toBeVisible();
    await expect(page.getByText("You could consider it now")).toHaveCount(0);
    await expect(page.getByText("Confirm the conditions first").first()).toBeVisible();
  });

  test("answers stay in this tab, can be cleared, and never reach the web server", async ({ page }) => {
    const seen: string[] = [];
    page.on("request", (r) => seen.push(`${r.url()} ${r.postData() ?? ""}`));
    await page.goto("/offers/match");
    await basics(page, { history: "2_5y", spend: "7373", opened: "2", marks: "no" });
    await check(page);
    await expect(page.getByRole("heading", { name: /^Results/ })).toBeVisible();
    expect(seen.filter((u) => u.startsWith("http://127.0.0.1:3010")).some((u) => u.includes("7373"))).toBe(false);
    await page.reload();
    await expect(page.getByLabel("How long have you had credit?")).toHaveValue("2_5y");
    await page.getByRole("button", { name: "Clear my answers" }).click();
    await expect(page.getByLabel("How long have you had credit?")).toHaveValue("");
    await page.reload();
    await expect(page.getByLabel("How long have you had credit?")).toHaveValue("");
  });

  test("from an offer page: check only that offer", async ({ page }) => {
    await page.goto("/offers");
    await page.getByRole("link", { name: /Details and history for Example Bank Everyday Cash Card/ }).first().click();
    await page.getByRole("link", { name: "Check this offer for me" }).click();
    await expect(page).toHaveURL(/\/offers\/match\?campaign=/);
    await expect(page.getByLabel("Only the offer I came from")).toBeChecked();
    await basics(page, { history: "5y_plus", spend: "3000", opened: "1", marks: "no" });
    await check(page);
    await expect(page.getByRole("heading", { name: "Results (1)" })).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(1);
  });
});
