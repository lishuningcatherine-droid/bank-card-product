import type { Campaign } from "@/lib/api/types";

/** Campaign status chip (DESIGN §27.3). Every chip carries its word; colour is never the only signal. */
const STYLE: Record<string, string> = {
  active: "bg-navy-50 text-navy-900",
  ending_soon: "bg-warning-bg text-warning",
  expired: "bg-expired-bg text-expired",
  withdrawn: "bg-expired-bg text-expired",
  pending_verification: "bg-recheck-bg text-recheck",
  stale: "bg-warning-bg text-warning",
};

export function CampaignStatus({ c }: { c: Pick<Campaign, "status" | "status_label" | "status_reason"> }) {
  return (
    <span title={c.status_reason ?? undefined} className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${STYLE[c.status] ?? STYLE.stale}`}>
      {c.status_label}
    </span>
  );
}

/** Where the information comes from, and whether the issuer confirms it. */
export function SourceBadge({ c }: { c: Pick<Campaign, "source_kind" | "source_label" | "source_name"> }) {
  const cls = c.source_kind === "third_party" ? "bg-unverified-bg text-unverified" : "bg-surface-subtle text-ink-700 border border-border";
  return (
    <span className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${cls}`}>
      {c.source_label}{c.source_name ? `: ${c.source_name}` : ""}
    </span>
  );
}

export function DemoBadge() {
  return <span className="inline-flex items-center rounded-sm bg-warning-bg px-2 py-0.5 text-xs font-medium text-warning">Demo data — not a real offer</span>;
}
