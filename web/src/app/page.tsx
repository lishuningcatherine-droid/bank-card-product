import Link from "next/link";

import { CampaignCard } from "@/components/CampaignCard";
import { OfferAmount } from "@/components/OfferAmount";
import { RankedOfferCard } from "@/components/RankedOfferCard";
import { EmptyState, ErrorState } from "@/components/States";
import { getRankedOffers, listCampaigns } from "@/lib/api/server";
import type { Campaign, PublicOffers } from "@/lib/api/types";

const DEPOSIT_TYPES = [
  ["checking", "Checking accounts", "/checking-accounts"],
  ["savings", "Savings accounts", "/savings-accounts"],
] as const;
type T = (typeof DEPOSIT_TYPES)[number][0];
type SP = Record<string, string | string[] | undefined>;

function CampaignList({ id, title, intro, items }: { id: string; title: string; intro: string; items: Campaign[] }) {
  return (
    <div className="space-y-3">
      <h3 id={`${id}-h`} className="text-xl">{title}</h3>
      <p className="text-sm text-ink-700">{intro}</p>
      {items.length ? (
        <ul aria-labelledby={`${id}-h`} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map((c) => <li key={c.id}><CampaignCard c={c} /></li>)}
        </ul>
      ) : <p className="text-sm text-ink-500">None right now.</p>}
    </div>
  );
}

export default async function Home({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const type: T = sp.type === "savings" ? "savings" : "checking";
  let campaigns: Campaign[] | null = null;
  let deposits: PublicOffers | null = null;
  const [c, d] = await Promise.allSettled([listCampaigns(new URLSearchParams({ sort: "deadline" })), getRankedOffers(type, "value", "cash")]);
  if (c.status === "fulfilled") campaigns = c.value.items;
  if (d.status === "fulfilled") deposits = d.value;
  const ending = (campaigns ?? []).filter((x) => x.status === "ending_soon");
  const cash = (campaigns ?? []).filter((x) => x.status !== "ending_soon" && (x.terms.unit === "cash" || x.terms.unit === "statement_credit")).slice(0, 6);
  const points = (campaigns ?? []).filter((x) => x.status !== "ending_soon" && x.terms.unit !== "cash" && x.terms.unit !== "statement_credit").slice(0, 6);
  const browse = DEPOSIT_TYPES.find((t) => t[0] === type)!;
  return (
    <div className="space-y-10">
      <section className="max-w-3xl">
        <h1 className="text-4xl leading-tight">Credit card offers worth knowing about right now</h1>
        <p className="mt-4 text-lg">
          Current welcome offers from the issuers&apos; own pages, with what each one takes, its deadline in Eastern
          time when the issuer states one, its key limits and its history on this site. Then check whether an offer
          suits your credit history, recent applications and spending before you apply.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/offers" className="inline-flex min-h-11 items-center rounded-md bg-navy-900 px-6 font-medium text-white no-underline hover:bg-navy-700">
            See all current offers
          </Link>
          <Link href="/offers/match" className="inline-flex min-h-11 items-center rounded-md border border-border px-6 font-medium no-underline hover:border-border-strong">
            Check which offers fit me
          </Link>
        </div>
      </section>

      <section id="offers" aria-labelledby="offers-h" className="space-y-6">
        <h2 id="offers-h" className="text-2xl">Current credit card offers</h2>
        {campaigns === null ? (
          <ErrorState>We couldn&apos;t load offers right now. Please try again in a moment.</ErrorState>
        ) : campaigns.length === 0 ? (
          <EmptyState title="No tracked offers yet" href="/credit-cards" cta="Browse credit cards">Offers appear once their official pages have been read and verified.</EmptyState>
        ) : (
          <>
            {ending.length ? <CampaignList id="ending" title="Ending soon" intro="Offers whose issuer-stated deadline is within the next 14 days." items={ending} /> : null}
            <CampaignList id="cash" title="Cash back offers" intro="Paid in dollars or statement credits." items={cash} />
            <CampaignList id="points" title="Points and miles offers" intro="Shown in points or miles; a dollar figure only where an official page states a cash value." items={points} />
            <p className="text-sm"><Link href="/offers" className="underline">All {campaigns.length} current offers, with filters</Link> · <Link href="/rules" className="underline">Application rules</Link></p>
          </>
        )}
      </section>

      <section id="deposits" aria-labelledby="deposits-h" className="space-y-4">
        <h2 id="deposits-h" className="text-2xl">Bank account bonuses</h2>
        <nav aria-label="Account type" className="flex flex-wrap gap-2">
          {DEPOSIT_TYPES.map(([t, label]) => (
            <Link key={t} href={`/?type=${t}#deposits`} aria-current={t === type ? "page" : undefined}
              className={`inline-flex min-h-11 items-center rounded-md border px-4 text-sm font-medium no-underline ${t === type ? "border-navy-900 bg-navy-900 text-white" : "border-border text-ink-700 hover:border-border-strong"}`}>
              {label}
            </Link>
          ))}
        </nav>
        {deposits === null ? (
          <ErrorState>We couldn&apos;t load account bonuses right now.</ErrorState>
        ) : deposits.items.length === 0 ? (
          <EmptyState title="No public bonus right now" href={browse[2]} cta={`Browse all ${browse[1].toLowerCase()}`}>
            No Verified {browse[1].toLowerCase()} show a current public bonus on their official pages.
          </EmptyState>
        ) : (
          <ol className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {deposits.items.map((it) => <li key={it.offer.id}><RankedOfferCard item={it} /></li>)}
          </ol>
        )}
        {deposits?.unranked.length ? (
          <div className="rounded-md border border-border p-4 text-sm">
            <h3 className="text-base">Bonuses without a fixed amount</h3>
            <ul className="mt-2 space-y-1">
              {deposits.unranked.map((u) => (
                <li key={u.offer.id}><Link href={`/products/${u.product.id}`} className="underline">{u.product.name}</Link> ({u.product.bank_name}): <OfferAmount offer={u.offer} /></li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="text-sm"><Link href={browse[2]} className="underline">Browse all {browse[1].toLowerCase()}</Link> · <Link href="/recommend" className="underline">Personal recommendations</Link></p>
      </section>
    </div>
  );
}
