import Link from "next/link";

import type { Campaign } from "@/lib/api/types";
import { longDate, usd } from "@/lib/format";

import { CampaignStatus, DemoBadge, SourceBadge } from "./CampaignStatus";
import { ComponentsList, offerAmountText, spendText } from "./CampaignTerms";
import { Countdown } from "./Countdown";
import { SourceLink } from "./SourceLink";

/** One campaign in the current-offers list: what it is, what it takes, until when, its limits, and its source. */
export function CampaignCard({ c, pv }: { c: Campaign; pv?: string }) {
  const t = c.terms;
  const spend = spendText(t);
  const href = `/offers/${c.id}${pv ? `?pv=${encodeURIComponent(pv)}` : ""}`;
  return (
    <article className="flex h-full flex-col rounded-lg border border-border bg-surface p-5 shadow-card">
      <div className="flex flex-wrap items-center gap-2">
        <CampaignStatus c={c} />
        <span className="text-xs text-ink-500">{c.channel_label} · {c.card.segment === "business" ? "Business card" : "Personal card"}</span>
        {c.demo ? <DemoBadge /> : null}
      </div>
      <p className="mt-3 text-sm text-ink-500">{c.card.bank_name}</p>
      <h3 className="mt-0.5 text-lg leading-snug">
        <Link href={href} className="text-ink-900 no-underline hover:underline">{c.card.name}</Link>
      </h3>
      <p className="mt-2 text-base font-medium text-ink-900">{c.offer_type_label}: {offerAmountText(t)}{t.tiers.length > 1 ? ` in ${t.tiers.length} tiers` : ""}</p>
      <ComponentsList t={t} />
      {spend ? <p className="text-sm text-ink-700">{spend}</p> : null}
      <dl className="mt-3 space-y-1 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-500">Application deadline</dt>
          <dd className="text-right text-ink-900">{c.deadline_label}{c.countdown_to ? <span className="block"><Countdown to={c.countdown_to} /></span> : null}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-500">First-year annual fee</dt>
          <dd className="tabular text-right">{t.first_year_fee_cents == null ? "Not stated" : usd(t.first_year_fee_cents)}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-500">{c.value.depends_on_points_value ? "Value (assumption below)" : "Reward value"}</dt>
          <dd className="tabular text-right text-ink-900">{c.value.cents == null ? "No dollar value" : usd(c.value.cents)}</dd>
        </div>
        {c.value.first_year_net_cents != null ? (
          <div className="flex justify-between gap-3 font-medium">
            <dt className="text-ink-700">Value minus first-year fee</dt>
            <dd className="tabular text-right text-ink-900">{usd(c.value.first_year_net_cents)}</dd>
          </div>
        ) : null}
      </dl>
      {c.value.assumption ? <p className="mt-1 text-xs text-ink-500">{c.value.assumption}</p> : null}
      <p className="mt-2 text-xs text-ink-700">{c.history.text}</p>
      {t.eligibility_text ? <p className="mt-2 line-clamp-3 text-xs text-ink-700"><span className="font-medium">Key limits: </span>{t.eligibility_text}</p> : null}
      <div className="mt-auto space-y-1 pt-3 text-xs text-ink-500">
        <SourceBadge c={c} />
        <p>Last verified {c.last_verified_at ? longDate(c.last_verified_at) : "—"} · first seen by this site {longDate(c.first_seen_at)}</p>
        <div className="flex items-center justify-between gap-3 text-sm">
          <Link href={href} className="font-medium">Details and history<span className="sr-only"> for {c.card.name}</span></Link>
          {t.offer_url ? <SourceLink href={t.offer_url}>Source</SourceLink> : null}
        </div>
      </div>
    </article>
  );
}
