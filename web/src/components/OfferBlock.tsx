"use client";

import { useSyncExternalStore } from "react";

import type { Offer } from "@/lib/api/types";
import { longDate } from "@/lib/format";

import { OfferAmount, OfferTiers } from "./OfferAmount";
import { SourceLink } from "./SourceLink";
import { StatusLabel } from "./StatusLabel";

/** Who an offer is for. Only public offers are ranked or recommended; the others are shown with this label. */
export const AUDIENCE: Record<string, string> = {
  targeted: "Targeted offer — only for selected recipients",
  referral: "Referral offer — only through a referral link",
  preapproved: "Pre-approved offer — only for invited applicants",
};

const CHANNEL: Record<string, string> = {
  product_page: "product page",
  offer_page: "offer page",
  comparison_page: "comparison page",
  terms_page: "terms page",
  manual_capture: "manual capture of an official page",
};

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

/** "creditcards.chase.com/rewards-credit-cards/sapphire/preferred" from the offer's official URL. */
export function pageLabel(url: string): string {
  try {
    const u = new URL(url);
    return (u.host + u.pathname).replace(/\/$/, "");
  } catch {
    return url;
  }
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
      {offer.audience && offer.audience !== "public" ? (
        <p><StatusLabel status="uncertain">{AUDIENCE[offer.audience] ?? "Not a public offer"}</StatusLabel></p>
      ) : null}
      <p>
        <span className="text-ink-500">{TYPE[offer.offer_type] ?? "Offer"}: </span>
        <OfferAmount offer={offer} />
      </p>
      {!compact ? (
        <>
          <OfferTiers offer={offer} />
          <blockquote className="border-l-2 border-border pl-3 text-ink-700">{offer.verbatim_text}</blockquote>
          {offer.note ? <p className="text-ink-500">{offer.note}</p> : null}
          {offer.eligibility_restrictions ? <p className="text-ink-500">{offer.eligibility_restrictions}</p> : null}
          {/* Offers can differ by entry point: say which official page showed this one, and when. */}
          {(offer.seen_on?.length ?? 0) > 1 ? (
            <div className="text-xs text-ink-500">
              <p>This offer was shown on {offer.seen_on!.length} official pages:</p>
              <ul className="list-disc pl-5">
                {offer.seen_on!.map((s) => (
                  <li key={s.url}>
                    <SourceLink href={s.url}>{pageLabel(s.url)}</SourceLink>
                    {s.channel ? ` (${CHANNEL[s.channel] ?? s.channel})` : ""}
                    {s.last_confirmed_at ? ` as of ${longDate(s.last_confirmed_at)}` : ""}
                  </li>
                ))}
              </ul>
              {offer.expiration_date ? <p>Expires {longDate(offer.expiration_date)}</p> : null}
            </div>
          ) : (
            <p className="text-xs text-ink-500">
              Offer shown on <SourceLink href={offer.offer_url}>{pageLabel(offer.offer_url)}</SourceLink> as of{" "}
              {longDate(offer.last_confirmed_at)}
              {offer.expiration_date ? ` · Expires ${longDate(offer.expiration_date)}` : ""}
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}
