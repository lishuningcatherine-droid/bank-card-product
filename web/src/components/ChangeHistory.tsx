import type { HistoryEntry } from "@/lib/api/types";
import { longDate } from "@/lib/format";

const NAMES: Record<string, string> = {
  annual_fee_cents: "Annual fee", apy_pct: "APY", monthly_fee_cents: "Monthly fee", purchase_apr_min_pct: "Purchase APR (low)",
  purchase_apr_max_pct: "Purchase APR (high)", reward_rates: "Reward rates", foreign_tx_fee_pct: "Foreign transaction fee",
  status: "Offer status",
};

function show(field: string, v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (field.endsWith("_cents") && typeof v === "number") return `$${(v / 100).toLocaleString("en-US")}`;
  if (field.endsWith("_pct")) return `${v}%`;
  if (typeof v === "object") return "updated";
  return String(v);
}

export function ChangeHistory({ entries }: { entries: HistoryEntry[] }) {
  return (
    <section aria-labelledby="history">
      <h2 id="history" className="text-xl">Change history</h2>
      {entries.length === 0 ? <p className="mt-2 text-sm">No changes recorded yet.</p> : (
        <ol className="mt-3 space-y-3">
          {entries.map((e) => (
            <li key={`${e.kind}-${e.version}-${e.date}`} className="rounded-md border border-border p-3 text-sm">
              <p className="font-medium text-ink-900">
                <time dateTime={e.date}>{longDate(e.date)}</time> — {e.change_class === "initial" ? (e.kind === "offer" ? "Offer first published" : "First published") : e.kind === "offer" ? "Offer updated" : "Product updated"}
              </p>
              {e.change_class !== "initial" && e.changes.length ? (
                <ul className="mt-1 list-disc pl-5">
                  {e.changes.map((c, i) => (
                    <li key={i}>
                      {NAMES[String(c.field)] ?? String(c.field).replaceAll("_", " ")}: {show(String(c.field), c.old)} → {show(String(c.field), c.new)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
