import type { Metadata } from "next";

import { PageTitle } from "@/components/Site";
import { ErrorState } from "@/components/States";
import { getSources } from "@/lib/api/server";
import type { SourcesResponse } from "@/lib/api/types";
import { longDate, TYPE_LABEL } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Data sources", description: "Which banks and product types are covered, and their current status." };

const AVAIL: Record<string, string> = { offered: "Offered", not_offered: "Not offered", unknown: "Not yet confirmed" };

export default async function Sources() {
  let data: SourcesResponse | null = null;
  try { data = await getSources(); } catch { data = null; }
  if (!data) return (<><PageTitle title="Data sources" /><ErrorState /></>);
  return (
    <div className="space-y-8">
      <PageTitle title="Data sources" intro="We read official bank pages only. Products appear after their pages are retrieved and verified. Bank names are shown in plain text; we have no relationship with any bank." />
      {data.banks.map((b) => (
        <section key={b.bank_id} aria-labelledby={`b-${b.bank_id}`} className="rounded-lg border border-border p-5">
          <h2 id={`b-${b.bank_id}`} className="text-xl">{b.display_name}</h2>
          <p className="text-sm text-ink-500">Official domains: {b.official_domains.join(", ")}</p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead><tr className="text-ink-500"><th scope="col" className="py-1 text-left font-normal">Product type</th><th scope="col" className="text-left font-normal">Availability</th><th scope="col" className="text-right font-normal">Verified</th><th scope="col" className="text-right font-normal">Partially verified</th><th scope="col" className="text-right font-normal">Last run</th></tr></thead>
              <tbody className="divide-y divide-border">
                {(["credit_card", "checking", "savings"] as const).map((t) => {
                  const c = b.published_counts[t] ?? { verified: 0, partially_verified: 0 };
                  const s = b.summary.find((x) => x.product_type === t) as { last_run_at?: string } | undefined;
                  return (
                    <tr key={t}>
                      <th scope="row" className="py-1 text-left font-normal">{TYPE_LABEL[t]}</th>
                      <td>{AVAIL[String(b.product_types[t]?.availability ?? "unknown")]}</td>
                      <td className="text-right tabular">{c.verified ?? 0}</td>
                      <td className="text-right tabular">{c.partially_verified ?? 0}</td>
                      <td className="text-right tabular">{s?.last_run_at ? longDate(s.last_run_at) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {b.known_limitations.length ? (
            <details className="mt-3 text-sm"><summary className="cursor-pointer font-medium text-ink-900">Known limitations</summary>
              <ul className="mt-1 list-disc pl-5">{b.known_limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
          ) : null}
        </section>
      ))}
      <section>
        <h2 className="text-xl">Cross-check sources</h2>
        <ul className="mt-2 list-disc pl-5">{data.cross_check_sources.map((c) => <li key={c.name}>{c.name}: {c.use}</li>)}</ul>
        <ul className="mt-4 list-disc pl-5 text-sm">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </section>
    </div>
  );
}
