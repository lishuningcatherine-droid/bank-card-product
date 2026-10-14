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
  if (p.product_type === "checking") {
    return [
      { label: "Monthly fee", value: val(d.monthly_fee_cents, (x) => usd(x as number)) },
      { label: "Minimum opening deposit", value: val(d.min_opening_deposit_cents, (x) => usd(x as number)) },
      { label: "Fee waivers", value: Array.isArray(d.fee_waivers) && d.fee_waivers.length ? `${d.fee_waivers.length} ways to waive` : d.monthly_fee_cents === 0 ? "Not needed" : missing },
    ];
  }
  const tiers = d.apy_tiers as { apy_pct: string }[] | null;
  return [
    { label: "APY", value: d.apy_pct != null ? <span className="tabular">{pct(d.apy_pct as string)}</span> : tiers?.length ? <span className="tabular">{pct(tiers[0]!.apy_pct)}–{pct(tiers[tiers.length - 1]!.apy_pct)} by balance</span> : missing },
    { label: "Monthly fee", value: val(d.monthly_fee_cents, (x) => usd(x as number)) },
    { label: "Minimum opening deposit", value: val(d.min_opening_deposit_cents, (x) => usd(x as number)) },
  ];
}
