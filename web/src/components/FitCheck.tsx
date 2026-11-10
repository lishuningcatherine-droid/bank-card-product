import Link from "next/link";

/** Entry point to the personal check for one offer (the check itself runs on /offers/match; no data leaves the
 * browser except the answers sent to compute the result, which are not stored). */
export function FitCheck({ campaignId }: { campaignId: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-subtle p-4 text-sm">
      <p className="text-ink-700">
        Answer a few questions (credit history, recent applications, spending) to see whether you are likely to qualify
        for the bonus, whether you can meet the spending requirement naturally, and what to confirm first.
      </p>
      <Link href={`/offers/match?campaign=${encodeURIComponent(campaignId)}`} className="mt-3 inline-flex min-h-11 items-center rounded-md bg-navy-900 px-5 font-medium text-white no-underline hover:bg-navy-700">
        Check this offer for me
      </Link>
    </div>
  );
}
