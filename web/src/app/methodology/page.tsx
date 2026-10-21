import type { Metadata } from "next";

import { PageTitle } from "@/components/Site";
import { ErrorState } from "@/components/States";
import { getMethodology } from "@/lib/api/server";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Methodology", description: "How offers are ranked, how values are estimated and how verification works." };

export default async function Methodology() {
  let m: Record<string, unknown> | null = null;
  try { m = await getMethodology(); } catch { m = null; }
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
