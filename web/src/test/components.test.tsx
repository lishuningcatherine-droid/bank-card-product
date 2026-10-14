import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OfferAmount, UP_TO_TOOLTIP } from "@/components/OfferAmount";
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
  it("names the official page the offer came from", () => {
    expect(pageLabel("https://creditcards.chase.com/rewards-credit-cards/sapphire/preferred")).toBe(
      "creditcards.chase.com/rewards-credit-cards/sapphire/preferred",
    );
  });
});
