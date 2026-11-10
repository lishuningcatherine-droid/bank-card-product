import type { Metadata } from "next";
import Link from "next/link";

import { CampaignCard } from "@/components/CampaignCard";
import { Disclaimer } from "@/components/Disclaimer";
import { PointValueForm, pvFromParams } from "@/components/PointValueForm";
import { EmptyState, ErrorState } from "@/components/States";
import { getPointValues, listCampaigns } from "@/lib/api/server";
import type { Campaign, CampaignPage, PointValue } from "@/lib/api/types";

export const metadata: Metadata = {
  title: "Current credit card offers",
  description: "Current welcome offers on major U.S. credit cards: what they pay, what they take, until when, their limits and their official sources.",
};

type SP = Record<string, string | string[] | undefined>;
const FILTERS = ["bank", "segment", "offer_type", "annual_fee_max", "min_spend_max", "deadline", "include_past", "sort"] as const;
const BANKS = [
  ["american_express", "American Express"], ["bank_of_america", "Bank of America"], ["capital_one", "Capital One"],
  ["chase", "Chase"], ["citi", "Citi"], ["discover", "Discover"], ["wells_fargo", "Wells Fargo"],
] as const;

function Select({ name, label, value, options }: { name: string; label: string; value?: string; options: readonly (readonly [string, string])[] }) {
  return (
    <label className="flex flex-col text-sm font-medium text-ink-900">
      {label}
      <select name={name} defaultValue={value ?? ""} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal text-ink-900">
        <option value="">Any</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function Section({ id, title, intro, items, pv }: { id: string; title: string; intro: string; items: Campaign[]; pv: string }) {
  return (
    <section aria-labelledby={`${id}-h`} className="space-y-3">
      <h2 id={`${id}-h`} className="text-2xl">{title}</h2>
      <p className="text-sm text-ink-700">{intro}</p>
      {items.length ? (
        <ul aria-label={title} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map((c) => <li key={c.id}><CampaignCard c={c} pv={pv} /></li>)}
        </ul>
      ) : <p className="text-sm text-ink-500">None match these filters.</p>}
    </section>
  );
}

export default async function OffersPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const params: Record<string, string> = {};
  for (const k of FILTERS) {
    const v = sp[k];
    if (typeof v === "string" && v) params[k] = v;
  }
  const { pv, values } = pvFromParams(sp);
  const qs = new URLSearchParams(params);
  if (pv) qs.set("pv", pv);
  let data: CampaignPage | null = null;
  let programs: PointValue[] = [];
  try {
    [data, programs] = await Promise.all([listCampaigns(qs), getPointValues()]);
  } catch {
    data = null;
  }
  const cash = data?.items.filter((c) => c.terms.unit === "cash" || c.terms.unit === "statement_credit") ?? [];
  const points = data?.items.filter((c) => c.terms.unit !== "cash" && c.terms.unit !== "statement_credit") ?? [];
  const keep = { ...params };
  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-3xl">Current credit card offers</h1>
        <p className="mt-3 text-ink-700">
          Welcome offers on the cards this site tracks, read from the issuers&apos; own pages. Each offer shows what it
          takes, its application deadline in Eastern time (only when the issuer states one), its key limits, where the
          information comes from and when it was last verified. No personal information is needed to browse.
        </p>
        <p className="mt-3"><Link href="/offers/match" className="font-medium">Check which offers fit you →</Link></p>
      </header>

      <form method="get" action="/offers" aria-label="Filters" className="rounded-lg border border-border bg-surface-subtle p-4">
        {Object.entries(values).map(([k, v]) => <input key={k} type="hidden" name={`v_${k}`} value={v} />)}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Select name="bank" label="Bank" value={params.bank} options={BANKS} />
          <Select name="segment" label="Personal or business" value={params.segment} options={[["consumer", "Personal cards"], ["business", "Business cards"]]} />
          <Select name="offer_type" label="Offer type" value={params.offer_type} options={[["welcome_bonus", "Welcome bonus"], ["spend_multiplier", "Limited-time earn boost"], ["first_year_fee", "First-year fee offer"], ["first_year_match", "First-year rewards match"]]} />
          <Select name="annual_fee_max" label="Maximum annual fee" value={params.annual_fee_max} options={[["0", "No annual fee"], ["100", "Up to $100"], ["400", "Up to $400"], ["800", "Up to $800"]]} />
          <Select name="min_spend_max" label="Maximum spending requirement" value={params.min_spend_max} options={[["500", "Up to $500"], ["1500", "Up to $1,500"], ["4000", "Up to $4,000"], ["8000", "Up to $8,000"]]} />
          <Select name="deadline" label="Application deadline" value={params.deadline} options={[["known", "Deadline stated"], ["within_30", "Ends within 30 days"], ["unknown", "No deadline stated"]]} />
          <Select name="sort" label="Sort by" value={params.sort} options={[["recent", "Recently verified"], ["deadline", "Deadline"], ["value", "Value (where stated)"], ["spend", "Lowest spending requirement"]]} />
          <label className="flex items-center gap-2 self-end text-sm font-medium text-ink-900">
            <input type="checkbox" name="include_past" value="true" defaultChecked={params.include_past === "true"} className="h-5 w-5" />
            Include expired and withdrawn offers
          </label>
        </div>
        <div className="mt-3 flex gap-3">
          <button type="submit" className="inline-flex min-h-11 items-center rounded-md bg-navy-900 px-5 font-medium text-white hover:bg-navy-700">Apply filters</button>
          <Link href="/offers" className="inline-flex min-h-11 items-center text-sm">Clear filters</Link>
        </div>
      </form>

      {programs.length ? <PointValueForm programs={programs} current={values} action="/offers" keep={keep} /> : null}

      {data === null ? (
        <ErrorState>We couldn&apos;t load offers right now. Please try again in a moment.</ErrorState>
      ) : data.items.length === 0 ? (
        <EmptyState title="No offers match these filters" href="/offers" cta="Clear filters">Try fewer filters.</EmptyState>
      ) : (
        <>
          <p className="text-sm text-ink-700" aria-live="polite">{data.total} offer{data.total === 1 ? "" : "s"}</p>
          <Section id="cash" title="Cash back and statement-credit offers" intro="Paid in dollars; the value is the stated amount." items={cash} pv={pv} />
          <Section id="points" title="Points and miles offers" intro="Shown in points or miles. A dollar figure appears only where an official page states a cash value, or where you enter your own value above." items={points} pv={pv} />
          <details className="rounded-md border border-border p-4 text-sm">
            <summary className="cursor-pointer font-medium text-ink-900">How these figures are worked out</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">{data.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            <p className="mt-2"><Link href="/methodology#offer-tracker" className="underline">Methodology</Link> · <Link href="/rules" className="underline">Application rules</Link></p>
          </details>
        </>
      )}
      <Disclaimer />
    </div>
  );
}
