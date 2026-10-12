import type { Metadata } from "next";
import Link from "next/link";

import { Disclaimer } from "@/components/Disclaimer";
import { OfferBlock } from "@/components/OfferBlock";
import { PageTitle } from "@/components/Site";
import { SourceLink } from "@/components/SourceLink";
import { EmptyState, ErrorState } from "@/components/States";
import { VerificationBadge } from "@/components/VerificationBadge";
import { compare } from "@/lib/api/server";
import type { CompareResponse } from "@/lib/api/types";
import { longDate, pct, usd } from "@/lib/format";

export const metadata: Metadata = { title: "Compare", description: "Side-by-side comparison of 2–4 products." };

const ROW_LABEL: Record<string, string> = {
  annual_fee_cents: "Annual fee", intro_annual_fee_cents: "First-year annual fee", reward_currency: "Reward type",
  base_rate: "Base rate", foreign_tx_fee_pct: "Foreign transaction fee", purchase_apr_min_pct: "Purchase APR (low)",
  purchase_apr_max_pct: "Purchase APR (high)", intro_purchase_apr_months: "Intro purchase APR (months)",
  intro_bt_apr_months: "Intro balance transfer APR (months)", bt_fee_pct: "Balance transfer fee", network: "Network",
  segment: "Consumer / business", is_co_branded: "Co-branded", is_student: "Student", is_secured: "Secured",
  monthly_fee_cents: "Monthly fee", min_opening_deposit_cents: "Minimum opening deposit", fee_waivers: "Fee waivers",
  overdraft_summary: "Overdraft", eligible_states: "States", access_model: "Branch / online", apy_pct: "APY",
  apy_tiers: "APY tiers", min_balance_cents: "Minimum balance", withdrawal_restrictions: "Withdrawals",
};

function cell(key: string, v: unknown): React.ReactNode {
  if (v === null || v === undefined) return <span className="text-ink-500">Information missing</span>;
  if (key.endsWith("_cents")) return <span className="tabular">{usd(v as number)}</span>;
  if (key.endsWith("_pct") || key === "base_rate") return <span className="tabular">{pct(v as string)}</span>;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" && x ? String((x as { text?: string; apy_pct?: string }).text ?? `${(x as { apy_pct?: string }).apy_pct}%`) : String(x))).join("; ");
  return String(v);
}

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ ids?: string }> }) {
  const ids = ((await searchParams).ids ?? "").split(",").filter(Boolean).slice(0, 4);
  if (ids.length < 2) {
    return (
      <>
        <PageTitle title="Compare products" />
        <EmptyState title="Choose 2 to 4 products to compare" href="/credit-cards" cta="Browse credit cards">
          Use the &ldquo;Compare&rdquo; checkbox on any product card.
        </EmptyState>
      </>
    );
  }
  let data: CompareResponse | null = null;
  try {
    data = await compare(ids);
  } catch {
    data = null;
  }
  if (!data) return (<><PageTitle title="Compare products" /><ErrorState>One or more products could not be loaded.</ErrorState></>);
  const items = data.items;
  return (
    <>
      <PageTitle title="Compare products" />
      {data.rows.length === 0 ? <p className="mb-4 text-sm">These products are different types, so only shared details are shown.</p> : null}
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Side-by-side comparison</caption>
          <thead className="bg-surface-subtle">
            <tr>
              <th scope="col" className="sticky left-0 bg-surface-subtle p-3 text-left">Detail</th>
              {items.map((p) => (
                <th key={p.id} scope="col" className="p-3 text-left align-top">
                  <span className="block text-xs font-normal text-ink-500">{p.bank_name}</span>
                  <Link href={`/products/${p.id}`}>{p.name}</Link>
                  <span className="mt-1 block"><VerificationBadge product={p} /></span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.rows.map((r) => (
              <tr key={r}>
                <th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium text-ink-900">{ROW_LABEL[r] ?? r}</th>
                {items.map((p) => <td key={p.id} className="p-3">{cell(r, (p.details as Record<string, unknown>)[r])}</td>)}
              </tr>
            ))}
            <tr>
              <th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium text-ink-900">Current offer</th>
              {items.map((p) => <td key={p.id} className="p-3">{p.offers?.[0] ? <OfferBlock offer={p.offers[0]} compact /> : <span className="text-ink-500">None found</span>}</td>)}
            </tr>
            <tr>
              <th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium text-ink-900">Last checked</th>
              {items.map((p) => <td key={p.id} className="p-3 tabular">{longDate(p.last_checked_at)}</td>)}
            </tr>
            <tr>
              <th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium text-ink-900">Source</th>
              {items.map((p) => <td key={p.id} className="p-3"><SourceLink href={p.official_url} /></td>)}
            </tr>
          </tbody>
        </table>
      </div>
      <div className="mt-6"><Disclaimer /></div>
    </>
  );
}
