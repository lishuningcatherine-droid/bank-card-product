import type { Metadata } from "next";

import { PageTitle } from "@/components/Site";
import { ErrorState } from "@/components/States";
import { getMethodology } from "@/lib/api/server";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Methodology", description: "How scores, values and verification work. All weights are public." };

type Weights = Record<string, number>;

function WeightTable({ title, weights }: { title: string; weights: Weights }) {
  return (
    <table className="w-full text-sm">
      <caption className="text-left font-medium text-ink-900">{title}</caption>
      <thead><tr className="text-ink-500"><th scope="col" className="py-1 text-left font-normal">Component</th><th scope="col" className="py-1 text-right font-normal">Weight</th></tr></thead>
      <tbody className="divide-y divide-border">
        {Object.entries(weights).map(([k, v]) => <tr key={k}><th scope="row" className="py-1 text-left font-normal">{k.replaceAll("_", " ")}</th><td className="py-1 text-right tabular">{v}</td></tr>)}
      </tbody>
    </table>
  );
}

export default async function Methodology() {
  let m: Record<string, unknown> | null = null;
  try { m = await getMethodology(); } catch { m = null; }
  const s = (m?.scoring ?? {}) as Record<string, { weights?: Weights }>;
  const pv = (m?.point_values ?? {}) as { default_cents_per_point?: number };
  return (
    <div className="max-w-3xl space-y-8">
      <PageTitle title="Methodology" intro="Recommendations are deterministic: the same inputs and data always give the same ranking. There is no machine learning and no paid placement." />
      <section className="space-y-2">
        <h2 className="text-xl">What can be recommended</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Only products labeled <strong>Verified</strong>: published from an official bank page, recently checked, with key fields confirmed.</li>
          <li>Only offers that are current, public, recently verified and not pending a recheck. Expired offers are evaluated at the time of your request and never shown as current.</li>
          <li>Partially verified products appear in browse and compare, with the missing items listed, but not in recommendations.</li>
        </ul>
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
      {m === null ? <ErrorState>The scoring configuration could not be loaded.</ErrorState> : (
        <section className="space-y-4">
          <h2 className="text-xl">Score weights</h2>
          {s.credit_card?.weights ? <WeightTable title="Credit cards" weights={s.credit_card.weights} /> : null}
          {s.checking?.weights ? <WeightTable title="Checking accounts" weights={s.checking.weights} /> : null}
          {s.savings?.weights ? <WeightTable title="Savings accounts" weights={s.savings.weights} /> : null}
        </section>
      )}
      <section className="space-y-2">
        <h2 className="text-xl">Freshness</h2>
        <p>APY sources are checked every 12 hours, offers daily and other terms weekly. Offers older than 14 days, APYs older than 7 days and terms older than 60 days are treated as not recently verified. Data is checked on a schedule; it is not continuously updated.</p>
      </section>
    </div>
  );
}
