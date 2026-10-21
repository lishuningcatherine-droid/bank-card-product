import type { Product } from "@/lib/api/types";
import { aprRange, CATEGORY_LABEL, pct, rateText, usd } from "@/lib/format";

type D = Record<string, unknown>;
const missing = <span className="text-ink-500">Information missing</span>;

function val(v: unknown, f: (x: unknown) => string): React.ReactNode {
  return v === null || v === undefined ? missing : <span className="tabular">{f(v)}</span>;
}

export function keyFacts(p: Product): { label: string; value: React.ReactNode }[] {
  const d = p.details as D;
  if (p.product_type === "credit_card") {
    const fee = d.annual_fee_cents as number | null;
    const intro = d.intro_annual_fee_cents as number | null | undefined;
    const top = [...(p.reward_rates ?? [])]
      .filter((r) => !r.portal_only)
      .sort((a, b) => Number(b.rate) - Number(a.rate))
      .slice(0, 2)
      .map((r) => `${rateText(r.rate, r.rate_unit)} ${CATEGORY_LABEL[r.category] ?? r.category}`);
    // A restricted-redemption currency (e.g. Disney Rewards Dollars) is never shown as cash back.
    const restricted =
      d.reward_currency === "restricted"
        ? [{
            label: "Rewards paid in",
            value: (
              <span>
                {String(d.reward_currency_name ?? "a store currency")}
                {d.redemption_value_cents != null ? ` (worth ${usd(d.redemption_value_cents as number)} each when redeemed as the issuer allows)` : ""}
                {d.redemption_restriction ? <span className="block text-ink-500">{String(d.redemption_restriction)}</span> : null}
              </span>
            ),
          }]
        : [];
    return [
      ...restricted,
      { label: "Annual fee", value: fee == null ? missing : <span className="tabular">{usd(fee)}{intro != null && intro !== fee ? ` (${usd(intro)} first year)` : ""}</span> },
      { label: "Rewards", value: top.length ? top.join(" · ") : d.rewards_program === "none" ? "No rewards program" : missing },
      { label: "Purchase APR", value: aprRange(d.purchase_apr_min_pct, d.purchase_apr_max_pct) ?? "See issuer" },
      { label: "Foreign transaction fee", value: d.foreign_tx_fee_pct == null ? "See issuer" : val(d.foreign_tx_fee_pct, (x) => (Number(x) === 0 ? "None" : pct(x as string))) },
    ];
  }
  const tiers = d.apy_tiers as Tier[] | null;
  if (p.product_type === "checking") {
    return [
      { label: "Monthly fee", value: val(d.monthly_fee_cents, (x) => usd(x as number)) },
      ...introWaiver(d),
      { label: "Minimum opening deposit", value: openingDeposit(d.min_opening_deposit_cents) },
      { label: "Fee waivers", value: Array.isArray(d.fee_waivers) && d.fee_waivers.length ? `${d.fee_waivers.length} ways to waive` : d.monthly_fee_cents === 0 ? "Not needed" : missing },
      ...(tiers?.length ? [{ label: "Interest (APY)", value: tierList(tiers) }] : []),
      ...whoCanOpen(d.customer_eligibility),
    ];
  }
  return [
    { label: "APY", value: d.apy_pct != null ? <span className="tabular">{pct(d.apy_pct as string)}</span> : tiers?.length ? tierList(tiers) : missing },
    { label: "Monthly fee", value: val(d.monthly_fee_cents, (x) => usd(x as number)) },
    ...introWaiver(d),
    { label: "Minimum opening deposit", value: openingDeposit(d.min_opening_deposit_cents) },
    ...whoCanOpen(d.customer_restrictions),
  ];
}

/** Not a Verified requirement (owner decision 2026-10-20): when unstated, say so instead of "Information missing". */
export function openingDeposit(v: unknown): React.ReactNode {
  return v == null ? <span className="text-ink-500">Not stated — confirm with the bank</span> : <span className="tabular">{usd(v as number)}</span>;
}

type Tier = { min_balance_cents: number; max_balance_cents: number | null; apy_pct: string };
type IntroWaiver = { count: number; unit: string; qualifier: string; text: string };

/** Balance tiers as stated: one rate for all balances, or each band with its APY. */
export function tierList(tiers: Tier[]): React.ReactNode {
  if (tiers.length === 1 && tiers[0]!.min_balance_cents === 0 && tiers[0]!.max_balance_cents == null) {
    return <span className="tabular">{pct(tiers[0]!.apy_pct)} on all balances</span>;
  }
  return (
    <ul className="tabular">
      {tiers.map((t) => (
        <li key={t.min_balance_cents}>
          {t.max_balance_cents == null ? `${usd(t.min_balance_cents)} and over` : `${usd(t.min_balance_cents)}–${usd(t.max_balance_cents)}`}: {pct(t.apy_pct)}
        </li>
      ))}
    </ul>
  );
}

/** "Waived for the first 2 statement periods": the unit as the bank states it (never converted to months). */
export function introWaiverText(w: IntroWaiver): string {
  const unit = w.unit === "statement_period" ? "statement period" : "month";
  return `Waived for ${w.qualifier === "at_least" ? "at least " : ""}the first ${w.count} ${unit}${w.count === 1 ? "" : "s"}`;
}

function introWaiver(d: D) {
  const w = d.intro_fee_waiver as IntroWaiver | null | undefined;
  return w?.count ? [{ label: "New accounts", value: <span title={`“${w.text}”`}>{introWaiverText(w)}</span> }] : [];
}

function whoCanOpen(v: unknown) {
  return typeof v === "string" && v ? [{ label: "Who can open", value: <span className="block text-left">{v}</span> }] : [];
}
