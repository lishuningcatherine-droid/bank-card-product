"use client";

import { useId, useState } from "react";

import type { Offer } from "@/lib/api/types";

/** The ONLY component that reads offer amounts. An "up to" maximum is never shown without "Up to" or as dollars. */
export const UP_TO_TOOLTIP =
  "The bank says this offer can vary. The amount you're offered is shown during your application and may be lower than this maximum.";

function amountText(unit: string, n: number): string {
  if (unit === "cents") return `$${Math.floor(n / 100).toLocaleString("en-US")}`;
  return `${n.toLocaleString("en-US")} ${unit}`;
}

type Tier = { amount: number; requirement_min_cents?: number | null; window_count?: number | null; window_unit?: string | null; incremental?: boolean; text?: string };

/** One line per tier: "70,000 miles after you spend $3,000 in 3 months"; a non-spend tier keeps the page's wording
 * ("10,000 miles after you add an authorized user …") and is marked as not counted. A tier's amount is never shown
 * with another tier's requirement. */
export function tierLine(unit: string, t: Tier): { text: string; counted: boolean } {
  const amt = amountText(unit, t.amount);
  if (t.requirement_min_cents != null) {
    const when = t.window_count ? ` in ${t.window_count} ${(t.window_unit ?? "").replace("_", " ")}` : "";
    const spend = `$${Math.floor(t.requirement_min_cents / 100).toLocaleString("en-US")}`;
    return { text: `${amt} after you spend ${t.incremental ? "another " : ""}${spend}${when}`, counted: true };
  }
  const cond = /\b(after you .+?)(?:[.*]|$)/i.exec(t.text ?? "")?.[1];
  return { text: cond ? `${amt} ${cond}` : `${amt} for a non-spending activity`, counted: false };
}

export function OfferTiers({ offer }: { offer: Pick<Offer, "amount_qualifier" | "reward_unit" | "tiers"> }) {
  if (offer.amount_qualifier !== "tiered" || !offer.tiers?.length) return null;
  return (
    <ul className="list-disc pl-5 text-ink-700">
      {(offer.tiers as Tier[]).map((t, i) => {
        const l = tierLine(offer.reward_unit, t);
        return (
          <li key={i} className="tabular">
            {l.text}
            {l.counted ? null : <span className="text-ink-500"> (not counted in recommendations)</span>}
          </li>
        );
      })}
    </ul>
  );
}

export function OfferAmount({ offer }: { offer: Pick<Offer, "amount_qualifier" | "amount_min" | "amount_max" | "reward_unit"> }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (offer.amount_qualifier === "exact" && offer.amount_max != null) {
    return <span className="tabular font-semibold">{amountText(offer.reward_unit, offer.amount_max)}</span>;
  }
  if (offer.amount_qualifier === "tiered" && offer.amount_max != null) {
    // Tiered offer: the maximum needs every tier; recommendations count only tiers your spending reaches.
    return (
      <span className="tabular font-semibold">
        <strong>Up to</strong> {amountText(offer.reward_unit, offer.amount_max)} in tiers
      </span>
    );
  }
  if (offer.amount_qualifier === "starting_at" && offer.amount_min != null) {
    return <span className="tabular font-semibold">At least {amountText(offer.reward_unit, offer.amount_min)}</span>;
  }
  if (offer.amount_qualifier === "up_to" && offer.amount_max != null) {
    return (
      <span className="relative inline-flex items-center gap-1">
        <span className="tabular font-semibold">
          <strong>Up to</strong> {amountText(offer.reward_unit, offer.amount_max)}
        </span>
        <button
          type="button"
          aria-label="About this offer amount"
          aria-expanded={open}
          aria-describedby={open ? id : undefined}
          onClick={() => setOpen((o) => !o)}
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          onBlur={() => setOpen(false)}
          className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-border-strong text-xs text-info"
        >
          i
        </button>
        {open ? (
          <span id={id} role="tooltip" className="absolute left-0 top-7 z-10 w-64 rounded-md bg-surface p-3 text-xs text-ink-700 shadow-raised">
            {UP_TO_TOOLTIP}
          </span>
        ) : null}
      </span>
    );
  }
  return <span>Amount not stated</span>;
}
