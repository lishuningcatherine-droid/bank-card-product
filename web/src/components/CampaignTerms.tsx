import type { CampaignTerms } from "@/lib/api/types";
import { usd } from "@/lib/format";

const UNIT: Record<string, string> = { cash: "cash back", statement_credit: "statement credit", points: "points", miles: "miles", free_night: "free night award", other: "" };
const START: Record<string, string> = {
  account_opening: "from account opening",
  card_membership: "of card membership",
  approval: "from approval",
  not_stated: "(start point not stated)",
};

/** "$200 cash back" | "75,000 points" — the reward in its own unit, never mixed into one number. */
export function rewardText(amount: number | null | undefined, unit: string, unitName?: string | null): string {
  if (amount === null || amount === undefined) return "Amount not stated";
  if (unit === "cash" || unit === "statement_credit") return `${usd(amount)} ${UNIT[unit]}`;
  return `${amount.toLocaleString("en-US")} ${unitName ?? UNIT[unit] ?? unit}`;
}

/** The offer's headline amount: a variable offer says "Up to …" (with its published minimum, if any), never a
 * guaranteed figure. */
export function offerAmountText(t: Pick<CampaignTerms, "total_amount" | "unit" | "unit_name" | "amount_qualifier" | "guaranteed_min">): string {
  const base = rewardText(t.total_amount, t.unit, t.unit_name);
  if (t.total_amount == null) return base;
  if (t.amount_qualifier === "up_to") {
    return t.guaranteed_min != null
      ? `Up to ${base} (at least ${rewardText(t.guaranteed_min, t.unit, t.unit_name)})`
      : `Up to ${base} (varies by applicant; no guaranteed minimum)`;
  }
  if (t.amount_qualifier === "starting_at") return `At least ${base}`;
  return base;
}

/** Restricted parts of an offer (e.g. a travel credit), each with its restriction and expiry; never added to the
 * reward and never shown as cash. */
export function ComponentsList({ t }: { t: Pick<CampaignTerms, "offer_components"> }) {
  const comps = t.offer_components ?? [];
  if (!comps.length) return null;
  return (
    <ul className="mt-1 space-y-1 text-sm">
      {comps.map((c, i) => (
        <li key={i}>
          <span className="font-medium text-ink-900">Plus {usd(c.amount_cents)} restricted credit</span>: for {c.restriction}
          {c.expires ? `, ${c.expires}` : ""}. <span className="text-ink-500">Not cash and not converted to points; not counted in the value.</span>
        </li>
      ))}
    </ul>
  );
}

/** "Spend $4,000 within 3 months from account opening" (the qualifying period, not the application deadline). */
export function spendText(t: Pick<CampaignTerms, "min_spend_cents" | "window_count" | "window_unit" | "window_start">): string | null {
  if (t.min_spend_cents === null || t.min_spend_cents === undefined) return null;
  const unit = (t.window_unit ?? "").replaceAll("_", " ");
  const when = t.window_count ? ` within ${t.window_count} ${unit} ${START[t.window_start] ?? ""}` : " (period not stated)";
  return `Spend ${usd(t.min_spend_cents)}${when}`.trim();
}

export function TiersList({ t }: { t: CampaignTerms }) {
  if (t.tiers.length < 2) return null;
  return (
    <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-sm">
      {t.tiers.map((x, i) => (
        <li key={i}>
          {rewardText(x.amount, x.unit, x.unit_name)}
          {x.spend_cents != null ? ` after ${x.incremental ? "another " : ""}${usd(x.spend_cents)}` : ""}
          {x.window_count ? ` within ${x.window_count} ${(x.window_unit ?? "").replaceAll("_", " ")}` : ""}
        </li>
      ))}
    </ol>
  );
}
