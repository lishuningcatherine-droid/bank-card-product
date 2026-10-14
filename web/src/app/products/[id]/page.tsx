import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ChangeHistory } from "@/components/ChangeHistory";
import { CheckedAgo } from "@/components/CheckedAgo";
import { Disclaimer } from "@/components/Disclaimer";
import { OfferBlock } from "@/components/OfferBlock";
import { keyFacts } from "@/components/ProductFacts";
import { SourceLink } from "@/components/SourceLink";
import { StatusLabel } from "@/components/StatusLabel";
import { VerificationBadge } from "@/components/VerificationBadge";
import { ApiError, getHistory, getProduct } from "@/lib/api/server";
import type { Product } from "@/lib/api/types";
import { CATEGORY_LABEL, CONDITION_LABEL, RESTRICTIVE, TYPE_LABEL, usd } from "@/lib/format";

type Props = { params: Promise<{ id: string }> };

async function load(id: string): Promise<Product> {
  try {
    return await getProduct(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  try {
    const p = await getProduct((await params).id);
    return { title: `${p.name} (${p.bank_name})`, description: `${TYPE_LABEL[p.product_type]} from ${p.bank_name}: fees, rates and offers with official sources.` };
  } catch {
    return { title: "Product" };
  }
}

export default async function ProductPage({ params }: Props) {
  const { id } = await params;
  const p = await load(id);
  const history = await getHistory(id).catch(() => []);
  const d = p.details as Record<string, unknown>;
  const missingFields = p.missing_fields ?? [];
  const offers = p.offers ?? [];
  const rates = p.reward_rates ?? [];
  const benefits = p.benefits ?? [];
  return (
    <article className="space-y-8">
      <header>
        <p className="text-sm text-ink-500">{p.bank_name} · {TYPE_LABEL[p.product_type]}</p>
        <h1 className="mt-1 text-3xl">{p.name}</h1>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <VerificationBadge product={p} />
          {p.recheck_pending ? <StatusLabel status="recheck">Recheck pending — this changed on the bank&apos;s site and we&apos;re confirming it</StatusLabel> : null}
        </div>
        <div className="mt-3"><CheckedAgo checkedAt={p.last_checked_at} changedAt={p.last_changed_at} /></div>
        <p className="mt-2 text-sm">
          <SourceLink href={p.official_url} />
          {p.terms_url ? <> · <SourceLink href={p.terms_url}>Terms</SourceLink></> : null}
        </p>
      </header>

      <section aria-labelledby="facts" className="grid gap-6 md:grid-cols-2">
        <div>
          <h2 id="facts" className="text-xl">Key facts</h2>
          <dl className="mt-3 divide-y divide-border rounded-md border border-border text-sm">
            {keyFacts(p).map((f) => (
              <div key={f.label} className="flex justify-between gap-4 p-3">
                <dt className="text-ink-500">{f.label}</dt>
                <dd className="text-right text-ink-900">{f.value}</dd>
              </div>
            ))}
            {p.product_type === "credit_card" && d.secured_min_deposit_cents != null ? (
              <div className="flex justify-between gap-4 p-3"><dt className="text-ink-500">Minimum security deposit</dt><dd className="tabular">{usd(d.secured_min_deposit_cents as number)}</dd></div>
            ) : null}
            {p.product_type === "credit_card" && d.secured_max_deposit_cents != null ? (
              <div className="flex justify-between gap-4 p-3"><dt className="text-ink-500">Maximum security deposit</dt><dd className="tabular">{usd(d.secured_max_deposit_cents as number)}</dd></div>
            ) : null}
            {p.product_type === "credit_card" && d.au_fee_cents != null ? (
              <div className="flex justify-between gap-4 p-3"><dt className="text-ink-500">Authorized users</dt><dd className="tabular">{d.au_fee_cents === 0 ? "No fee" : usd(d.au_fee_cents as number)}{d.au_free_count ? ` (up to ${String(d.au_free_count)} free)` : ""}</dd></div>
            ) : null}
            {d.future_annual_fee_cents != null ? (
              <div className="flex justify-between gap-4 p-3"><dt className="text-ink-500">Scheduled fee change</dt><dd className="tabular">{usd(d.future_annual_fee_cents as number)} from {String(d.annual_fee_effective_date)}</dd></div>
            ) : null}
          </dl>
          {missingFields.length ? <p className="mt-2 text-sm"><StatusLabel status="missing" /> Not found on the source page: {missingFields.join(", ").replaceAll("_", " ")}.</p> : null}
        </div>
        <div>
          <h2 className="text-xl">Current offer</h2>
          <div className="mt-3 rounded-md border border-border p-4">
            {offers.length ? offers.map((o) => <OfferBlock key={o.id} offer={o} />) : (
              <p className="text-sm">{p.offer_absent_note ?? "No public offer was found on the official page when we last checked."}</p>
            )}
          </div>
        </div>
      </section>

      {rates.length ? (
        <section aria-labelledby="rewards">
          <h2 id="rewards" className="text-xl">Rewards</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {rates.map((r, i) => (
              <li key={i} className="rounded-md border border-border p-3">
                <span className="font-medium text-ink-900">{CATEGORY_LABEL[r.category] ?? r.category}</span>: {r.text}
                <span className="mt-1 flex flex-wrap gap-2">
                  {r.portal_only ? <StatusLabel status="missing">Portal only — counted only if you opt in</StatusLabel> : null}
                  {(r.conditions ?? []).filter((c) => c.kind !== "portal_only").map((c, j) => (
                    <span key={j} title={`“${c.text}”`}>
                      <StatusLabel status={RESTRICTIVE.has(c.kind) ? "missing" : "stale"}>
                        {CONDITION_LABEL[c.kind] ?? c.kind}{c.detail ? ` (${c.detail})` : ""}
                      </StatusLabel>
                    </span>
                  ))}
                  {r.requires_activation && !(r.conditions ?? []).some((c) => c.kind === "enrollment_required") ? <StatusLabel status="stale">Activation required</StatusLabel> : null}
                  {r.ends_on ? <StatusLabel status="stale">Ends {r.ends_on}</StatusLabel> : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {benefits.length ? (
        <section aria-labelledby="benefits">
          <h2 id="benefits" className="text-xl">Benefits and credits</h2>
          <ul className="mt-3 list-disc pl-5 text-sm">
            {benefits.map((b) => <li key={b.id}>{b.name}{b.monetizable && b.annual_value_cents ? ` — up to ${usd(b.annual_value_cents)} a year if you use it` : ""}{b.enrollment_required ? " (enrollment required)" : ""}</li>)}
          </ul>
        </section>
      ) : null}

      <ChangeHistory entries={history} />
      <Disclaimer />
    </article>
  );
}
