import { render, screen } from "@testing-library/react";

import { CampaignCard } from "@/components/CampaignCard";
import { rewardText, spendText } from "@/components/CampaignTerms";
import { RuleKind } from "@/components/RuleList";
import type { Campaign } from "@/lib/api/types";

vi.mock("next/link", () => ({ default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));

const UNKNOWN = { date: null, time: null, time_known: false, stated_tz: null, text: null, confirmed: false, label: "Deadline unknown" };

function campaign(over: Partial<Campaign> = {}, terms: Partial<Campaign["terms"]> = {}): Campaign {
  return {
    id: "00000000-0000-0000-0000-000000000001", campaign_key: "example_bank:card|public|welcome_bonus|points:1:spend",
    card: { card_key: "example_bank:card", product_id: "p1", name: "Example Bank Voyager Rewards Card", bank_id: "example_bank", bank_name: "Example Bank",
      segment: "consumer", series: null, points_program: "example_points", points_program_name: null, official_url: null, annual_fee_cents: 9500,
      first_year_fee_cents: 9500, reports_to_personal_credit: null, counts_toward_chase_524: null, demo: true },
    channel: "public", channel_label: "Public application", offer_type: "welcome_bonus", offer_type_label: "Welcome bonus",
    status: "active", status_label: "Active", status_reason: "shown on the official page at the last successful check",
    source_kind: "official", source_label: "Official page (read automatically)", source_name: null, officially_verified: true,
    first_seen_at: "2026-11-01T12:00:00Z", last_checked_at: "2026-11-09T12:00:00Z", last_verified_at: "2026-11-09T12:00:00Z", version: 1,
    terms: { offer_type: "welcome_bonus", channel: "public", tiers: [], amount_qualifier: "exact", total_amount: 60000, unit: "points", unit_name: null,
      stated_cash_value_cents: null, min_spend_cents: 400000, window_count: 3, window_unit: "months", window_start: "account_opening",
      annual_fee_cents: 9500, first_year_fee_cents: 9500, start: null, end: UNKNOWN, eligibility_text: "Not available if you have had this card.",
      cap_text: null, categories: [], verbatim: null, offer_url: "https://www.examplebank.example/cards/voyager", ...terms },
    deadline_label: "Deadline unknown", countdown_to: null,
    value: { cents: null, depends_on_points_value: true, assumption: "No dollar value: no official cash-redemption value for these points (enter your own)",
      cents_per_point: null, first_year_net_cents: null, first_year_fee_cents: 9500 },
    history: { code: "insufficient_history", text: "Not enough history recorded on this site yet (1 record(s) over 0 month(s); comparisons need 3 records over 12 months).",
      records: 1, coverage_months: 0, median: null, official_only: false },
    demo: true,
    ...over,
  } as Campaign;
}

describe("CampaignCard (acceptance: deadlines, sources, status, assumptions)", () => {
  it("an unknown deadline shows no end time and no countdown", () => {
    const { container } = render(<CampaignCard c={campaign()} />);
    expect(screen.getByText("Deadline unknown")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/left|23:59|ends in/i);
  });

  it("a date without a published time is never shown as 23:59", () => {
    const end = { ...UNKNOWN, date: "2026-12-05", confirmed: true, label: "Deadline 2026-12-05 (time not published)" };
    const { container } = render(<CampaignCard c={campaign({ deadline_label: end.label }, { end })} />);
    expect(screen.getByText("Deadline 2026-12-05 (time not published)")).toBeInTheDocument();
    expect(container.textContent).not.toContain("23:59");
  });

  it("a stated time is shown in ET", () => {
    const end = { ...UNKNOWN, date: "2026-12-05", time: "23:59", time_known: true, stated_tz: "ET", confirmed: true, label: "Deadline: 2026-12-05 23:59 ET" };
    render(<CampaignCard c={campaign({ deadline_label: end.label }, { end })} />);
    expect(screen.getByText("Deadline: 2026-12-05 23:59 ET")).toBeInTheDocument();
  });

  it("shows source, last verification, status and the demo label", () => {
    render(<CampaignCard c={campaign({ status: "stale", status_label: "Data out of date" })} />);
    expect(screen.getByText("Official page (read automatically)")).toBeInTheDocument();
    expect(screen.getByText(/Last verified Nov 9, 2026/)).toBeInTheDocument();
    expect(screen.getByText("Data out of date")).toBeInTheDocument();
    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
  });

  it("points without an official value show no dollar figure and say why", () => {
    render(<CampaignCard c={campaign()} />);
    expect(screen.getByText("No dollar value")).toBeInTheDocument();
    expect(screen.getByText(/no official cash-redemption value/)).toBeInTheDocument();
  });

  it("never shows a comparative history label without enough history", () => {
    const { container } = render(<CampaignCard c={campaign()} />);
    expect(container.textContent).toContain("Not enough history recorded on this site yet");
    expect(container.textContent).not.toMatch(/highest|better than usual/i);
  });
});

describe("terms wording", () => {
  it("keeps units apart and states the spending period's start", () => {
    expect(rewardText(20000, "cash")).toBe("$200 cash back");
    expect(rewardText(60000, "points")).toBe("60,000 points");
    expect(spendText({ min_spend_cents: 400000, window_count: 3, window_unit: "months", window_start: "account_opening" })).toBe("Spend $4,000 within 3 months from account opening");
    expect(spendText({ min_spend_cents: 100000, window_count: 3, window_unit: "months", window_start: "not_stated" })).toContain("start point not stated");
  });

  it("labels official and community rules differently", () => {
    const { rerender } = render(<RuleKind r={{ source_type: "official", verification: "page_captured" }} />);
    expect(screen.getByText("Official bank rule")).toBeInTheDocument();
    rerender(<RuleKind r={{ source_type: "community", verification: "community_report" }} />);
    expect(screen.getByText(/Community-reported rule/)).toBeInTheDocument();
  });
});
