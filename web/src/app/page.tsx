import Link from "next/link";

import { OfferAmount } from "@/components/OfferAmount";
import { RankedOfferCard } from "@/components/RankedOfferCard";
import { EmptyState, ErrorState } from "@/components/States";
import { getRankedOffers } from "@/lib/api/server";
import type { OfferSort, PublicOffers } from "@/lib/api/types";

const TYPES = [
  ["credit_card", "Credit cards", "/credit-cards"],
  ["checking", "Checking accounts", "/checking-accounts"],
  ["savings", "Savings accounts", "/savings-accounts"],
] as const;
type T = (typeof TYPES)[number][0];

const SORTS: { value: OfferSort; label: string }[] = [
  { value: "value", label: "Estimated value" },
  { value: "bonus", label: "Largest bonus" },
  { value: "requirement", label: "Lowest requirement" },
  { value: "ending", label: "Ending soonest" },
];

type SP = Record<string, string | string[] | undefined>;

function pick<V extends string>(v: unknown, allowed: readonly V[], fallback: V): V {
  return typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as V) : fallback;
}

function OfferList({ id, title, intro, items }: { id: string; title?: string; intro?: string; items: PublicOffers["items"] }) {
  return (
    <div className="space-y-3" aria-labelledby={title ? `${id}-h` : undefined}>
      {title ? <h3 id={`${id}-h`} className="text-xl">{title}</h3> : null}
      {intro ? <p className="text-sm text-ink-700">{intro}</p> : null}
      {items.length ? (
        <ol className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map((it) => <li key={it.offer.id}><RankedOfferCard item={it} /></li>)}
        </ol>
      ) : <p className="text-sm text-ink-500">None right now.</p>}
    </div>
  );
}

export default async function Home({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const type = pick<T>(sp.type, TYPES.map((t) => t[0]), "credit_card");
  const sort = pick<OfferSort>(sp.sort, SORTS.map((s) => s.value), "value");
  // Cash offers and points/miles offers are never ranked together (owner decision 2026-10-20); deposit bonuses are cash.
  let data: PublicOffers | null = null;
  let points: PublicOffers | null = null;
  try {
    [data, points] = await Promise.all([
      getRankedOffers(type, sort, "cash"),
      type === "credit_card" ? getRankedOffers(type, sort, "points") : Promise.resolve(null),
    ]);
  } catch {
    data = null;
  }
  const href = (t: T, s: OfferSort) => `/?type=${t}${s === "value" ? "" : `&sort=${s}`}#offers`;
  const browse = TYPES.find((t) => t[0] === type)!;
  return (
    <div className="space-y-10">
      <section className="max-w-3xl">
        <h1 className="text-4xl leading-tight">Current public bank offers, with the sources in plain sight</h1>
        <p className="mt-4 text-lg">
          Browse the welcome offers and account bonuses that banks show to everyone on their official pages. Each estimate
          states its assumptions, and every offer links to the bank&apos;s page and shows when we last checked it.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/recommend" className="inline-flex min-h-11 items-center rounded-md bg-navy-900 px-6 font-medium text-white no-underline hover:bg-navy-700">
            Get personal recommendations
          </Link>
          <Link href="/methodology#public-offers" className="inline-flex min-h-11 items-center rounded-md border border-border px-6 font-medium no-underline hover:border-border-strong">
            How offers are ranked
          </Link>
        </div>
      </section>

      <section id="offers" aria-labelledby="offers-h" className="space-y-4">
        <h2 id="offers-h" className="text-2xl">Public offers</h2>
        <nav aria-label="Product type" className="flex flex-wrap gap-2">
          {TYPES.map(([t, label]) => (
            <Link key={t} href={href(t, sort)} aria-current={t === type ? "page" : undefined}
              className={`inline-flex min-h-11 items-center rounded-md border px-4 text-sm font-medium no-underline ${t === type ? "border-navy-900 bg-navy-900 text-white" : "border-border text-ink-700 hover:border-border-strong"}`}>
              {label}
            </Link>
          ))}
        </nav>
        <nav aria-label="Sort offers" className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-ink-500">Sort by:</span>
          {SORTS.map((s) => (
            <Link key={s.value} href={href(type, s.value)} aria-current={s.value === sort ? "true" : undefined}
              className={s.value === sort ? "font-semibold text-ink-900 no-underline" : "text-navy-700"}>
              {s.label}
            </Link>
          ))}
        </nav>
        {data === null ? (
          <ErrorState>We couldn&apos;t load offers right now. Please try again in a moment.</ErrorState>
        ) : data.items.length === 0 && !points?.items.length ? (
          <EmptyState title="No public bonus right now" href={browse[2]} cta={`Browse all ${browse[1].toLowerCase()}`}>
            No Verified {browse[1].toLowerCase()} show a current public bonus on their official pages.
          </EmptyState>
        ) : (
          <>
            <OfferList id="cash" title={type === "credit_card" ? "Cash offers" : undefined}
              intro={type === "credit_card" ? "Cash back and statement-credit bonuses, plus points with a cash value the issuer publishes as fixed." : undefined}
              items={data.items} />
            {points ? (
              <OfferList id="points" title="Points and miles offers"
                intro="Shown in points or miles. The dollar figure is only an estimate at the assumed value per point; these offers are ranked on their own, never against cash offers."
                items={points.items} />
            ) : null}
          </>
        )}
        {data?.unranked.length ? (
          <div className="rounded-md border border-border p-4 text-sm">
            <h3 className="text-base">Offers without a fixed amount (not ranked)</h3>
            <ul className="mt-2 space-y-1">
              {data.unranked.map((u) => (
                <li key={u.offer.id}>
                  <Link href={`/products/${u.product.id}`} className="underline">{u.product.name}</Link> ({u.product.bank_name}): <OfferAmount offer={u.offer} />
                  <span className="block text-ink-500">Not ranked: {u.reason}.</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {data ? (
          <details className="rounded-md border border-border p-4 text-sm">
            <summary className="cursor-pointer font-medium text-ink-900">Assumptions behind these estimates</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {data.assumptions.map((a) => <li key={a}>{a}</li>)}
            </ul>
            <p className="mt-2"><Link href="/methodology#public-offers" className="underline">Point values and full methodology</Link></p>
          </details>
        ) : null}
        <p className="text-sm"><Link href={browse[2]} className="underline">Browse all {browse[1].toLowerCase()}</Link>, including products without a current bonus.</p>
      </section>
    </div>
  );
}
