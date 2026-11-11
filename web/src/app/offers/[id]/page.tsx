import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CampaignStatus, DemoBadge, SourceBadge } from "@/components/CampaignStatus";
import { ComponentsList, offerAmountText, spendText, TiersList } from "@/components/CampaignTerms";
import { Countdown } from "@/components/Countdown";
import { Disclaimer } from "@/components/Disclaimer";
import { FitCheck } from "@/components/FitCheck";
import { RuleList } from "@/components/RuleList";
import { SourceLink } from "@/components/SourceLink";
import { ApiError, getCampaign } from "@/lib/api/server";
import type { CampaignDetail, CampaignTerms } from "@/lib/api/types";
import { longDate, usd } from "@/lib/format";

type Props = { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

async function load(id: string, pv?: string): Promise<CampaignDetail> {
  try {
    return await getCampaign(id, pv);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  try {
    const c = await getCampaign((await params).id);
    return { title: `${c.card.name}: ${c.offer_type_label.toLowerCase()}`, description: `${c.card.bank_name} offer, its conditions, deadline, limits, sources and history.` };
  } catch {
    return { title: "Offer" };
  }
}

const OUTCOME: Record<string, string> = {
  seen: "Shown on the official page",
  changed: "Shown, with changed terms (new version)",
  not_seen: "Official page captured, offer not shown",
  failed: "Check failed (page not read) — status kept",
  manual: "Entered by hand and reviewed",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 p-3 sm:grid-cols-[14rem_1fr]">
      <dt className="text-ink-500">{label}</dt>
      <dd className="text-ink-900">{children}</dd>
    </div>
  );
}

function TermsTable({ t }: { t: CampaignTerms }) {
  return (
    <dl className="divide-y divide-border rounded-md border border-border text-sm">
      <Row label="Reward">{offerAmountText(t)}<TiersList t={t} /><ComponentsList t={t} /></Row>
      <Row label="Spending requirement">{spendText(t) ?? "No spending requirement stated"}</Row>
      <Row label="Application deadline">{t.end.label}{t.end.text ? <span className="block text-xs text-ink-500">Issuer&apos;s words: “{t.end.text}”</span> : null}</Row>
      <Row label="Offer start">{t.start?.date ? `${t.start.date}${t.start.text ? ` — “${t.start.text}”` : ""}` : "Not stated by the issuer"}</Row>
      <Row label="Annual fee">{t.annual_fee_cents == null ? "Not stated" : usd(t.annual_fee_cents)}{t.first_year_fee_cents != null && t.first_year_fee_cents !== t.annual_fee_cents ? ` (first year ${usd(t.first_year_fee_cents)})` : ""}</Row>
      {t.cap_text ? <Row label="Cap">{t.cap_text}</Row> : null}
      <Row label="Eligibility and exclusions (issuer's words)">{t.eligibility_text ?? "None stated with the offer"}</Row>
      {t.verbatim ? <Row label="Offer text (issuer's words)">“{t.verbatim}”</Row> : null}
    </dl>
  );
}

export default async function CampaignPage({ params, searchParams }: Props) {
  const { id } = await params;
  const sp = await searchParams;
  const pv = typeof sp.pv === "string" ? sp.pv : undefined;
  const c = await load(id, pv);
  const t = c.terms;
  const official = c.rules.filter((r) => r.source_type === "official");
  const community = c.rules.filter((r) => r.source_type === "community");
  return (
    <article className="space-y-8">
      <header>
        <p className="text-sm text-ink-500">{c.card.bank_name} · {c.card.segment === "business" ? "Business card" : "Personal card"} · {c.channel_label}</p>
        <h1 className="mt-1 text-3xl">{c.card.name}: {offerAmountText(t)}</h1>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <CampaignStatus c={c} />
          <SourceBadge c={c} />
          {c.demo ? <DemoBadge /> : null}
        </div>
        {c.status_reason ? <p className="mt-2 text-sm text-ink-700">Status: {c.status_reason}.</p> : null}
        <p className="mt-2 text-sm text-ink-700">
          Last verified {c.last_verified_at ? longDate(c.last_verified_at) : "—"} · last checked {c.last_checked_at ? longDate(c.last_checked_at) : "—"} · first seen by this site {longDate(c.first_seen_at)} (not the bank&apos;s start date)
        </p>
        <p className="mt-2 text-sm">
          {t.offer_url ? <SourceLink href={t.offer_url}>Official offer page</SourceLink> : null}
          {c.card.product_id ? <> · <Link href={`/products/${c.card.product_id}`}>Card details and offer history</Link></> : null}
        </p>
      </header>

      <section aria-labelledby="terms-h" className="space-y-3">
        <h2 id="terms-h" className="text-xl">What the offer is and what it takes</h2>
        <TermsTable t={t} />
        {c.countdown_to ? <p className="text-sm">Time left (issuer stated date, time and zone): <Countdown to={c.countdown_to} /></p> : null}
        <p className="text-xs text-ink-500">The deadline is for applying. The spending period starts at the point stated above and is a separate limit.</p>
      </section>

      <section aria-labelledby="value-h" className="space-y-2">
        <h2 id="value-h" className="text-xl">Value</h2>
        <dl className="divide-y divide-border rounded-md border border-border text-sm">
          <Row label="Reward value">{c.value.cents == null ? "No dollar value" : usd(c.value.cents)}{c.value.assumption ? <span className="block text-xs text-ink-500">{c.value.assumption}</span> : null}</Row>
          <Row label="Minus first-year annual fee">{c.value.first_year_net_cents == null ? "—" : usd(c.value.first_year_net_cents)}{c.value.depends_on_points_value && c.value.first_year_net_cents != null ? <span className="block text-xs text-ink-500">Depends on the points value above.</span> : null}</Row>
          <Row label="Compared with this card's history">{c.history.text}</Row>
        </dl>
      </section>

      <section aria-labelledby="fit-h" className="space-y-3">
        <h2 id="fit-h" className="text-xl">Is this offer right for me?</h2>
        <FitCheck campaignId={c.id} />
      </section>

      <section aria-labelledby="rules-h" className="space-y-3">
        <h2 id="rules-h" className="text-xl">Application and bonus rules</h2>
        <h3 className="text-base">Published by {c.card.bank_name}</h3>
        <RuleList rules={official} />
        <h3 className="text-base">Reported by the community (not published by the bank)</h3>
        <RuleList rules={community} />
      </section>

      <section aria-labelledby="versions-h" className="space-y-3">
        <h2 id="versions-h" className="text-xl">Versions of this offer</h2>
        <p className="text-sm text-ink-700">A new version is recorded only when a term changes (amount, tiers, spending, period, fees, dates, eligibility or channel). Older versions are kept.</p>
        <ol className="space-y-4">
          {c.versions.map((v) => (
            <li key={v.version} className="rounded-md border border-border p-3">
              <p className="text-sm font-medium text-ink-900">Version {v.version}: {longDate(v.valid_from)} – {v.valid_to ? longDate(v.valid_to) : "current"}</p>
              {v.change_summary.length ? <p className="text-xs text-ink-500">Changed: {v.change_summary.map((ch) => String(ch.field).replaceAll("_", " ")).join(", ")}</p> : null}
              <div className="mt-2"><TermsTable t={v.terms} /></div>
              {v.source_url ? <p className="mt-1 text-xs"><SourceLink href={v.source_url}>Source</SourceLink></p> : null}
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="log-h" className="grid gap-6 md:grid-cols-2">
        <div>
          <h2 id="log-h" className="text-xl">Status changes</h2>
          <ol className="mt-2 space-y-2 text-sm">
            {c.status_log.map((s, i) => (
              <li key={i}><span className="tabular">{longDate(s.at)}</span>: {s.from_status ? `${s.from_status.replaceAll("_", " ")} → ` : ""}{s.to_status.replaceAll("_", " ")} ({s.trigger === "auto" ? "automatic" : `by ${s.actor ?? "a reviewer"}`}) — {s.reason}</li>
            ))}
          </ol>
        </div>
        <div>
          <h2 className="text-xl">Recent checks</h2>
          <ol className="mt-2 space-y-1 text-sm">
            {c.checks.map((k, i) => <li key={i}><span className="tabular">{longDate(k.at)}</span>: {OUTCOME[k.outcome] ?? k.outcome}</li>)}
          </ol>
        </div>
      </section>
      <Disclaimer />
    </article>
  );
}
