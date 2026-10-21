import Link from "next/link";

import type { Offer, RankedOffer } from "@/lib/api/types";
import { longDate, usd } from "@/lib/format";

import { OfferAmount, OfferTiers } from "./OfferAmount";
import { PlaceholderArt } from "./PlaceholderArt";
import { SourceLink } from "./SourceLink";

const REQUIREMENT: Record<string, string> = {
  spend: "spend",
  direct_deposit_total: "receive direct deposits of",
  new_money_deposit: "deposit new money of",
};

/** "after you spend $4,000 within 3 months", from the stored requirement and window (units as stated). */
export function requirementText(o: Pick<Offer, "requirement_type" | "requirement_min_cents" | "requirement_max_cents" | "requirement_qualifier" | "qualification_window_count" | "qualification_window_unit">): string | null {
  const cents = o.requirement_min_cents ?? o.requirement_max_cents;
  if (!o.requirement_type || cents == null) return null;
  const verb = REQUIREMENT[o.requirement_type] ?? o.requirement_type.replaceAll("_", " ");
  const upTo = o.requirement_qualifier === "up_to" ? "up to " : "";
  const unit = (o.qualification_window_unit ?? "").replaceAll("_", " ");
  const when = o.qualification_window_count ? ` within ${o.qualification_window_count} ${unit}` : "";
  return `after you ${verb} ${upTo}${usd(cents)}${when}`;
}

export function RankedOfferCard({ item }: { item: RankedOffer }) {
  const { product: p, offer: o, estimate: e } = item;
  const req = requirementText(o);
  const card = p.product_type === "credit_card";
  return (
    <article className="flex h-full flex-col rounded-lg border border-border bg-surface p-5 shadow-card">
      <PlaceholderArt type={p.product_type} className="max-w-32" />
      <p className="mt-3 text-sm text-ink-500">{p.bank_name}</p>
      <h3 className="mt-0.5 text-lg leading-snug">
        <Link href={`/products/${p.id}`} className="text-ink-900 no-underline hover:underline">{p.name}</Link>
      </h3>
      <p className="mt-2 text-sm">
        <OfferAmount offer={o} />
        {req ? <span className="text-ink-700"> {req}</span> : null}
      </p>
      <div className="text-sm"><OfferTiers offer={o} /></div>
      <dl className="mt-3 space-y-1 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-500">{e.group === "points" ? "Estimated value" : "Bonus value"}</dt>
          <dd className="tabular text-right text-ink-900">{usd(e.bonus_value_cents)}{e.value_basis !== "cash" ? <span className="block text-xs text-ink-500">{e.value_basis}</span> : null}</dd>
        </div>
        {card ? (
          <>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">First-year annual fee</dt>
              <dd className="tabular text-right">{e.first_year_fee_cents == null ? "Not stated" : usd(e.first_year_fee_cents)}</dd>
            </div>
            <div className="flex justify-between gap-3 font-medium">
              <dt className="text-ink-700">{e.group === "points" ? "Estimate minus first-year fee" : "Bonus minus first-year fee"}</dt>
              <dd className="tabular text-right text-ink-900">{e.net_first_year_cents == null ? "—" : usd(e.net_first_year_cents)}</dd>
            </div>
          </>
        ) : (
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Monthly fee</dt>
            <dd className="tabular text-right">{e.monthly_fee_cents == null ? "Not stated" : e.monthly_fee_cents === 0 ? "None" : <>{usd(e.monthly_fee_cents)}<span className="block text-xs text-ink-500">may be waived; not subtracted</span></>}</dd>
          </div>
        )}
      </dl>
      <p className="mt-2 text-xs text-ink-500">
        {o.expiration_date ? `Offer ends ${longDate(o.expiration_date)}. ` : "No end date stated. "}
        Shown on the bank&apos;s page as of {longDate(o.last_confirmed_at)}.
      </p>
      {item.other_public_offers?.length ? (
        <p className="mt-1 text-xs text-ink-500">
          {item.other_public_offers.length} other public offer{item.other_public_offers.length === 1 ? "" : "s"} on other official pages — see details.
        </p>
      ) : null}
      {item.non_public_offers ? (
        <p className="mt-1 text-xs text-ink-500">
          {item.non_public_offers} targeted, referral or pre-approved offer{item.non_public_offers === 1 ? "" : "s"} not ranked.
        </p>
      ) : null}
      <div className="mt-auto flex items-center justify-between gap-3 pt-3 text-sm">
        <Link href={`/products/${p.id}`} className="font-medium">Details<span className="sr-only"> for {p.name}</span></Link>
        <SourceLink href={o.offer_url}>Official offer page</SourceLink>
      </div>
    </article>
  );
}
