import type { Metadata } from "next";

import { PageTitle } from "@/components/Site";
import { ErrorState } from "@/components/States";
import { getMethodology, getPointValues } from "@/lib/api/server";
import type { PointValue } from "@/lib/api/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Methodology", description: "How offers are ranked, how values are estimated and how verification works." };

export default async function Methodology() {
  let m: Record<string, unknown> | null = null;
  try { m = await getMethodology(); } catch { m = null; }
  let floors: PointValue[] = [];
  try { floors = await getPointValues(); } catch { floors = []; }
  const factors = (m?.factors ?? {}) as Record<string, string[]>;
  const pv = (m?.point_values ?? {}) as { default_cents_per_point?: number; programs?: Record<string, { cents_per_point: number; basis?: string }> };
  const ranking = (m?.public_offer_ranking ?? []) as string[];
  return (
    <div className="max-w-3xl space-y-8">
      <PageTitle title="Methodology" intro="The default ranking is deterministic: the same answers and data always give the same order. There is no paid placement." />
      <section className="space-y-2">
        <h2 className="text-xl">What can be recommended</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Only products labeled <strong>Verified</strong>: published from an official bank page, recently checked, with key fields confirmed.</li>
          <li>Only offers that are current, public, recently verified and not pending a recheck. Expired offers are evaluated at the time of your request and never shown as current.</li>
          <li>Partially verified products appear in browse and compare, with the missing items listed, but not in recommendations.</li>
        </ul>
      </section>
      <section id="offer-tracker" className="space-y-3">
        <h2 className="text-xl">How current offers are tracked</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          <li><strong>Offers and cards are kept apart.</strong> A card&apos;s lasting features (fees, earn rates, benefits) are separate from its offers. One card can have several offers at once (for example a public offer and a targeted one) and many over time.</li>
          <li><strong>One offer, many versions.</strong> An offer is identified by its card, channel, type and reward structure. A new version is recorded only when a term changes: amount or unit, tiers, spending requirement, spending period, annual fee, start or end date, eligibility, or channel. Layout changes only update the verification time. Old versions are kept and shown.</li>
          <li><strong>Status.</strong> Active; Ending soon (an issuer-stated deadline within 14 days); Expired (only when an issuer-stated deadline has passed, or a reviewer confirms it); Withdrawn (only by a reviewer); Needs verification (the official page was read but no longer shows the offer); Data out of date (3 failed checks in a row, or no successful check for 7 days). A failed check never ends an offer. Every status change is logged with its reason and whether it was automatic or manual.</li>
          <li><strong>Deadlines</strong> are shown in US Eastern time. A time is shown only when the issuer states one (never filled in as 11:59 p.m.); a countdown only when the date, time and time zone are all stated. Without a date we say &ldquo;Deadline unknown&rdquo;. The date we first saw an offer is never presented as its start date. The application deadline is separate from the spending period after approval.</li>
          <li><strong>History.</strong> &ldquo;Usual level&rdquo; is the median of the public offers this site recorded for the card over the last 24 months. Labels such as &ldquo;highest&rdquo; or &ldquo;better than usual&rdquo; appear only with at least 3 records over at least 12 months, and always say they refer to this site&apos;s records. Third-party history is labelled and can be excluded.</li>
          <li><strong>Sources.</strong> Offers come from the issuers&apos; official pages. Offers we cannot read automatically (changed pages, targeted or branch offers) are entered by hand with their source and reviewed by a second person before they appear.</li>
        </ul>
        <h3 className="text-base">Conservative point values</h3>
        <p className="text-sm text-ink-700">Points and miles count only at the cash or statement-credit value an official page states. Without one, an offer shows its points and no dollar figure. You can enter your own value on the offers page.</p>
        <table className="w-full text-sm">
          <caption className="sr-only">Point value floors</caption>
          <thead><tr><th scope="col" className="py-1 text-left">Program</th><th scope="col" className="py-1 text-right">Value per point</th><th scope="col" className="py-1 pl-4 text-left">Basis</th></tr></thead>
          <tbody>
            {floors.map((f) => (
              <tr key={f.program}><th scope="row" className="py-1 text-left font-normal">{f.name}</th><td className="py-1 text-right tabular">{f.floor_cents == null ? "No dollar value" : `${f.floor_cents}¢`}</td><td className="py-1 pl-4">{f.excerpt ? <>“{f.excerpt}”{f.source_url ? <> (<a href={f.source_url} target="_blank" rel="noopener noreferrer">source</a>)</> : null}</> : f.note}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section id="public-offers" className="space-y-2">
        <h2 className="text-xl">How the home page ranks public offers</h2>
        <p>The home page ranks the offers banks show to everyone, without asking anything about you. It shows dollar estimates, never scores.</p>
        {ranking.length ? (
          <ul className="list-disc space-y-1 pl-5">{ranking.map((a) => <li key={a}>{a}</li>)}</ul>
        ) : null}
        <table className="w-full text-sm">
          <caption className="text-left font-medium text-ink-900">Point and mile values used in estimates</caption>
          <thead><tr className="text-ink-500"><th scope="col" className="py-1 text-left font-normal">Program</th><th scope="col" className="py-1 text-right font-normal">Cents each</th><th scope="col" className="py-1 text-left font-normal pl-4">Basis</th></tr></thead>
          <tbody className="divide-y divide-border">
            <tr><th scope="row" className="py-1 text-left font-normal">All programs not listed below</th><td className="py-1 text-right tabular">{pv.default_cents_per_point ?? 1}¢</td><td className="py-1 pl-4">default</td></tr>
            {Object.entries(pv.programs ?? {}).map(([k, v]) => (
              <tr key={k}><th scope="row" className="py-1 text-left font-normal">{k}</th><td className="py-1 text-right tabular">{v.cents_per_point}¢</td><td className="py-1 pl-4">{v.basis ?? ""}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="text-sm text-ink-500">A program gets its own value only when the issuer publishes a fixed cash-redemption value, and only those programs rank with cash offers. Every other point or mile (including hotel and airline programs) is ranked separately, shown in its own amount, and its dollar figure is labelled as an estimate at the default value. Targeted, referral and pre-approved offers are shown on product pages with that label, and are never ranked or recommended.</p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl">How value is counted</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li><strong>Ongoing annual value</strong>: recurring rewards or interest, plus statement credits you choose, minus recurring fees.</li>
          <li><strong>Promotional value</strong>: a one-time bonus, only when your inputs meet the requirement and the bank states an exact amount. &ldquo;Up to&rdquo; and &ldquo;at least&rdquo; offers add $0.</li>
          <li><strong>First-year value</strong>: ongoing + promotional + first-year fee differences. A bonus is never counted as recurring.</li>
          <li>Points and miles are valued at {pv.default_cents_per_point ?? 1}¢ each unless the issuer publishes a fixed cash value; you can change this on the results page. Portal-only and transfer-partner rates are not given extra value.</li>
          <li>Card rewards apply caps, combined caps and post-cap rates. Rotating categories count at the base rate unless you opt in.</li>
          <li>Checking bonuses show an explicit &ldquo;requirement achievable&rdquo; test from your direct deposits. Savings bonuses require both the new-money deposit and the holding period.</li>
        </ul>
      </section>
      {m === null ? <ErrorState>The methodology could not be loaded.</ErrorState> : (
        <section className="space-y-3">
          <h2 className="text-xl">What personal recommendations consider</h2>
          <p>Your answers are compared with each Verified product on these points. Results show dollar estimates and the reasons behind them, never a score.</p>
          {([["credit_card", "Credit cards"], ["checking", "Checking accounts"], ["savings", "Savings accounts"]] as const).map(([k, title]) => (
            factors[k]?.length ? (
              <div key={k}>
                <h3 className="text-base">{title}</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5">{factors[k]!.map((f) => <li key={f}>{f}</li>)}</ul>
              </div>
            ) : null
          ))}
        </section>
      )}
      <section className="space-y-2">
        <h2 className="text-xl">Freshness</h2>
        <p>APY sources are checked every 12 hours, offers daily and other terms weekly. Offers older than 14 days, APYs older than 7 days and terms older than 60 days are treated as not recently verified. Data is checked on a schedule; it is not continuously updated.</p>
      </section>
    </div>
  );
}
