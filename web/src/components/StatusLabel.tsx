export type Status = "expired" | "stale" | "recheck" | "missing" | "unverified" | "uncertain";

const STYLE: Record<Status, { cls: string; text: string }> = {
  expired: { cls: "bg-expired-bg text-expired", text: "Expired offer" },
  stale: { cls: "bg-warning-bg text-warning", text: "Offer not recently verified" },
  recheck: { cls: "bg-recheck-bg text-recheck", text: "Recheck pending" },
  missing: { cls: "bg-unverified-bg text-unverified", text: "Information missing" },
  unverified: { cls: "bg-unverified-bg text-unverified", text: "Not verified" },
  uncertain: { cls: "bg-warning-bg text-warning", text: "Offer varies — check the bank's site" },
};

export function StatusLabel({ status, children }: { status: Status; children?: React.ReactNode }) {
  const s = STYLE[status];
  return (
    <span className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      {children ?? s.text}
    </span>
  );
}
