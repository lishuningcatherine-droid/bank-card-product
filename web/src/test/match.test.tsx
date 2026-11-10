import { render, screen, within } from "@testing-library/react";

import { AssessmentCard, KindBadge } from "@/components/MatchCheck";
import type { Assessment, MatchFinding } from "@/lib/api/types";

vi.mock("next/link", () => ({ default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => <a href={href} {...p}>{children}</a> }));

function finding(over: Partial<MatchFinding> = {}): MatchFinding {
  return {
    rule_key: "example_once", name: "Example Bank: no bonus if you had this card", effect: "bonus", basis: "official",
    basis_label: "Issuer's published rule", verification: "page_captured", outcome: "conflict", outcome_label: "Conflict",
    explanation: "Met: you received the bonus on Example Bank Everyday Cash Card in 2021-06.", needs: [],
    excerpt: "Not available if you have had this card.", source_url: "https://www.examplebank.example/cards/everyday",
    source_title: null, verified_at: "2026-11-09", ...over,
  };
}

function assessment(over: Partial<Assessment> = {}): Assessment {
  const conflict = finding();
  return {
    campaign_id: "00000000-0000-0000-0000-000000000001", card_key: "example_bank:everyday-cash", card_name: "Example Bank Everyday Cash Card",
    bank_name: "Example Bank", action: "not_suitable", action_label: "Not a fit for now",
    action_reasons: ["Example Bank: no bonus if you had this card: Met: you received the bonus (issuer's published rule)"],
    conflicts: [conflict],
    approval: { status: "no_known_conflict", label: "No known rule conflict (approval is still the issuer's decision)", points: ["Only the issuer decides approval; this site does not estimate approval odds."] },
    bonus: { status: "known_conflict", label: "You are not eligible for this bonus by your answers", points: [] },
    offer_appeal: { status: "no_comparison", label: "Not enough history to compare", points: ["Offer: $2,000 after spending $500."] },
    personal_fit: { status: "good", label: "Fits your answers", points: [] },
    reach: { status: "sufficient", label: "Reachable with your normal spending", required_cents: 50000, needed_with_margin_cents: 60000,
      window: "3 months from account opening", projected_cents: 900000, text: "Your normal spending of $3,000 a month gives about $9,000.", tiers: [] },
    eligibility: [conflict, finding({ rule_key: "example_count", name: "Example 5/24-style count", effect: "approval", basis: "community",
      basis_label: "Community-reported rule (not published by the issuer)", outcome: "unknown", outcome_label: "Needs your answer",
      explanation: "Cannot tell.", needs: ["How many cards you opened"] })],
    uncertainty: ["How many cards you opened"],
    first_year: { reward_cents: 200000, first_year_fee_cents: 0, net_cents: 200000, depends_on_points_value: false, text: "First-year value: reward $2,000 − first-year fee $0 = $2,000." },
    ...over,
  };
}

describe("personal offer check", () => {
  it("lists a known conflict before the large reward and keeps approval and bonus apart", () => {
    render(<AssessmentCard a={assessment()} />);
    const card = screen.getByRole("article");
    const text = card.textContent ?? "";
    expect(text.indexOf("Known eligibility conflicts")).toBeLessThan(text.indexOf("First-year value"));
    expect(screen.getByText(/Suggested action: Not a fit for now/)).toBeInTheDocument();
    const approval = screen.getByRole("region", { name: "Can you be approved?" });
    const bonus = screen.getByRole("region", { name: "Can you earn this bonus?" });
    expect(within(approval).getByText(/approval is still the issuer's decision/)).toBeInTheDocument();
    expect(within(bonus).getByText(/not eligible for this bonus/)).toBeInTheDocument();
    expect(text).toContain("does not estimate approval odds");
  });

  it("marks official, community, answer-based and unconfirmed judgements differently", () => {
    render(<AssessmentCard a={assessment()} />);
    expect(screen.getAllByText("Official bank rule").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Community-reported rule").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Based on your answers").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not confirmed / not enough information").length).toBeGreaterThan(0);
  });

  it("states when a dollar figure depends on the value of points", () => {
    render(<AssessmentCard a={assessment({ first_year: { reward_cents: 60000, first_year_fee_cents: 9500, net_cents: 50500, depends_on_points_value: true,
      text: "First-year value: reward $600 − first-year fee $95 = $505. The reward part assumes: Counted at 1 point = $0.01 (cash redemption value stated by Example Bank)." } })} />);
    expect(screen.getByText(/1 point = \$0.01/)).toBeInTheDocument();
    expect(screen.getByText(/depends on the value of points/)).toBeInTheDocument();
  });

  it("badge texts are fixed", () => {
    render(<KindBadge kind="community" />);
    expect(screen.getByText("Community-reported rule")).toBeInTheDocument();
  });
});
