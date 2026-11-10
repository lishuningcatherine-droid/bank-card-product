import type { Metadata } from "next";
import Link from "next/link";

import { Disclaimer } from "@/components/Disclaimer";
import { KindBadge, MatchCheck } from "@/components/MatchCheck";
import { pvFromParams } from "@/components/PointValueForm";
import { PageTitle } from "@/components/Site";
import { ErrorState } from "@/components/States";
import { getTrackedCards } from "@/lib/api/server";
import type { CardSummary } from "@/lib/api/types";

export const metadata: Metadata = {
  title: "Is this offer right for me?",
  description: "Check current credit card offers against your credit history, recent applications and spending: eligibility rules, the spending requirement and what to confirm first.",
  robots: { index: false },
};

type SP = Record<string, string | string[] | undefined>;

export default async function MatchPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const campaign = typeof sp.campaign === "string" && /^[0-9a-f-]{36}$/.test(sp.campaign) ? sp.campaign : undefined;
  const { values } = pvFromParams(sp);
  const pointValues = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Number(v)]));
  let cards: CardSummary[];
  try {
    cards = await getTrackedCards();
  } catch {
    return <ErrorState>The offer data could not be loaded. Please try again later.</ErrorState>;
  }
  return (
    <>
      <PageTitle title="Is this offer right for me?"
        intro="Answer what you know. For each current offer you get six separate answers — offer appeal, personal fit, whether you can reach the spending requirement, known eligibility rules, what is uncertain, and a suggested action — with approval and bonus eligibility shown apart." />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-700">
        <span>Marks used:</span><KindBadge kind="official" /><KindBadge kind="community" /><KindBadge kind="profile" /><KindBadge kind="unconfirmed" />
      </div>
      <p className="mb-6 text-sm text-ink-700">Prefer to browse first? See <Link href="/offers">current offers</Link> or the <Link href="/rules">application rules</Link>.</p>
      <MatchCheck campaignId={campaign} pointValues={pointValues}
        cards={cards.map((c) => ({ card_key: c.card_key, bank_id: c.bank_id, name: `${c.bank_name} ${c.name}`, segment: c.segment }))} />
      <div className="mt-8"><Disclaimer /></div>
    </>
  );
}
