"use client";

import { useSyncExternalStore } from "react";

import type { Offer } from "@/lib/api/types";
import { longDate } from "@/lib/format";

import { OfferAmount } from "./OfferAmount";
import { SourceLink } from "./SourceLink";
import { StatusLabel } from "./StatusLabel";

const TYPE: Record<string, string> = {
  card_welcome: "Welcome offer", checking_bonus: "Checking bonus", savings_bonus: "Savings bonus",
  intro_apr: "Intro APR offer", annual_fee_waiver: "Annual fee offer",
};

/** Expiry is re-checked in the browser so a cached page never presents an expired offer as current. */
export function isExpired(expiration: string | null | undefined, now: Date = new Date()): boolean {
  if (!expiration) return false;
  const todayET = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(now);
  return expiration < todayET;
}

const noop = () => () => {};

/** Today's date in New York, read in the browser only (null during server rendering). */
function useTodayET(): string | null {
  return useSyncExternalStore(noop, () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date()), () => null);
}

export function OfferBlock({ offer, compact = false }: { offer: Offer; compact?: boolean }) {
  const today = useTodayET();
  const expiredNow = today !== null && !!offer.expiration_date && offer.expiration_date < today;
  const state = expiredNow ? "expired" : offer.state;
  if (state === "expired") {
    return (
      <div className="text-sm">
        <StatusLabel status="expired" />
      </div>
    );
  }
  if (state !== "current") {
    const s = state === "stale" ? "stale" : state === "recheck_pending" ? "recheck" : "uncertain";
    return (
      <div className="space-y-1 text-sm">
        <StatusLabel status={s} />
        <p className="text-ink-500">We couldn&apos;t verify this — check the bank&apos;s site.</p>
      </div>
    );
  }
  return (
    <div className="space-y-1 text-sm">
      <p>
        <span className="text-ink-500">{TYPE[offer.offer_type] ?? "Offer"}: </span>
        <OfferAmount offer={offer} />
      </p>
      {!compact ? (
        <>
          <blockquote className="border-l-2 border-border pl-3 text-ink-700">{offer.verbatim_text}</blockquote>
          {offer.note ? <p className="text-ink-500">{offer.note}</p> : null}
          {offer.eligibility_restrictions ? <p className="text-ink-500">{offer.eligibility_restrictions}</p> : null}
          <p className="text-xs text-ink-500">
            Verified {longDate(offer.last_confirmed_at)}
            {offer.expiration_date ? ` · Expires ${longDate(offer.expiration_date)}` : ""} ·{" "}
            <SourceLink href={offer.offer_url}>Offer source</SourceLink>
          </p>
        </>
      ) : null}
    </div>
  );
}
