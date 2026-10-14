import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OfferAmount, OfferTiers, UP_TO_TOOLTIP } from "@/components/OfferAmount";
import { keyFacts } from "@/components/ProductFacts";
import type { Product } from "@/lib/api/types";
import { isExpired, pageLabel } from "@/components/OfferBlock";
import { VerificationBadge } from "@/components/VerificationBadge";
import { usd, pct, relativeHours } from "@/lib/format";
import { decodeRequest, encodeRequest } from "@/lib/request-hash";

describe("OfferAmount", () => {
  it("renders exact amounts", () => {
    render(<OfferAmount offer={{ amount_qualifier: "exact", amount_min: 60000, amount_max: 60000, reward_unit: "points" }} />);
    expect(screen.getByText("60,000 points")).toBeInTheDocument();
  });

  it('always prefixes "Up to" and never converts points to dollars', () => {
    const { container } = render(<OfferAmount offer={{ amount_qualifier: "up_to", amount_min: null, amount_max: 80000, reward_unit: "points" }} />);
    expect(container.textContent).toMatch(/^Up to 80,000 points/);
    expect(container.textContent).not.toContain("$");
  });

  it("renders at-least amounts", () => {
    render(<OfferAmount offer={{ amount_qualifier: "starting_at", amount_min: 30000, amount_max: null, reward_unit: "cents" }} />);
    expect(screen.getByText("At least $300")).toBeInTheDocument();
  });

  it("toggletip opens with keyboard and closes with Escape", async () => {
    const user = userEvent.setup();
    render(<OfferAmount offer={{ amount_qualifier: "up_to", amount_min: null, amount_max: 30000, reward_unit: "cents" }} />);
    const btn = screen.getByRole("button", { name: "About this offer amount" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    btn.focus();
    await user.keyboard("{Enter}");
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("tooltip")).toHaveTextContent(UP_TO_TOOLTIP);
    expect(btn).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    fireEvent.keyDown(btn, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    await user.keyboard(" ");
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });
});

describe("request-time offer expiry", () => {
  it("uses the America/New_York date", () => {
    const lateEveningET = new Date("2026-10-13T03:00:00Z"); // 23:00 ET on Oct 12
    expect(isExpired("2026-10-12", lateEveningET)).toBe(false);
    expect(isExpired("2026-10-11", lateEveningET)).toBe(true);
    expect(isExpired(null, lateEveningET)).toBe(false);
  });
});

describe("VerificationBadge", () => {
  it("lists what is missing for partially verified products", () => {
    render(<VerificationBadge product={{ label: "partially_verified", label_reasons: ["information missing: fee waivers"] }} />);
    expect(screen.getByText(/Partially verified/)).toBeInTheDocument();
    expect(screen.getByText("information missing: fee waivers")).toBeInTheDocument();
  });
});

describe("format", () => {
  it("formats cents and percentages", () => {
    expect(usd(9500)).toBe("$95");
    expect(usd(123456)).toBe("$1,234.56");
    expect(usd(-14400)).toBe("−$144");
    expect(usd(null)).toBe("—");
    expect(pct("4.2000")).toBe("4.2%");
    expect(relativeHours("2026-10-12T00:00:00Z", new Date("2026-10-12T05:10:00Z"))).toBe("5 hours ago");
  });
});

describe("request hash", () => {
  it("round-trips inputs through the URL fragment", () => {
    const r = { product_type: "savings", deposit_range: "5k_25k", holding_months: 12, liquidity_need: "medium", max_monthly_fee: 0, apy_vs_bonus: "balanced" } as const;
    expect(decodeRequest(`#${encodeRequest(r)}`)).toEqual(r);
    expect(decodeRequest("#not-base64!")).toBeNull();
  });
});

describe("tiered offers and entry points (spot-check round 1)", () => {
  it("shows a tiered maximum as 'Up to ... in tiers', never as a flat amount", () => {
    render(<OfferAmount offer={{ amount_qualifier: "tiered", amount_min: 70000, amount_max: 80000, reward_unit: "miles" }} />);
    expect(screen.getByText(/in tiers/)).toHaveTextContent("Up to 80,000 miles in tiers");
  });
  it("lists each tier separately and never pairs the maximum with the first tier's spend", () => {
    const offer = {
      amount_qualifier: "tiered" as const, reward_unit: "miles",
      tiers: [
        { amount: 70000, requirement_min_cents: 300000, window_count: 3, window_unit: "months", text: "Earn 70,000 bonus miles after you spend $3,000" },
        { amount: 10000, requirement_min_cents: null, text: "Plus, earn 10,000 bonus miles after you add an authorized user to your account in the first 3 months your account is open.*" },
      ],
    };
    const { container } = render(<OfferTiers offer={offer} />);
    const items = [...container.querySelectorAll("li")].map((li) => li.textContent);
    expect(items).toEqual([
      "70,000 miles after you spend $3,000 in 3 months",
      "10,000 miles after you add an authorized user to your account in the first 3 months your account is open (not counted in recommendations)",
    ]);
    expect(container.textContent).not.toMatch(/80,000 miles after/);
  });
  it("names the official page the offer came from", () => {
    expect(pageLabel("https://creditcards.chase.com/rewards-credit-cards/sapphire/preferred")).toBe(
      "creditcards.chase.com/rewards-credit-cards/sapphire/preferred",
    );
  });
});

describe("restricted-redemption currency (DESIGN §24.19)", () => {
  it("names the currency and where it can be redeemed, never 'cash back'", () => {
    const p = {
      product_type: "credit_card",
      reward_rates: [{ category: "partner", rate: "10", rate_unit: "pct", portal_only: false }],
      details: {
        reward_currency: "restricted", reward_currency_name: "Disney Rewards Dollars", redemption_value_cents: 100,
        redemption_restriction: "Cardmembers can also redeem Rewards Dollars for a statement credit toward airline tickets purchased with your card.",
        annual_fee_cents: 14900,
      },
    } as unknown as Product;
    const facts = keyFacts(p);
    expect(facts[0]!.label).toBe("Rewards paid in");
    const { container } = render(<>{facts[0]!.value}</>);
    expect(container.textContent).toContain("Disney Rewards Dollars (worth $1 each");
    expect(container.textContent).toContain("airline tickets");
    expect(container.textContent).not.toMatch(/cash back/i);
  });
});
