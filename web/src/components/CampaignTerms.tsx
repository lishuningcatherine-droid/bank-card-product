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
