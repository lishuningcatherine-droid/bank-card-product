import type { ApplicationRule } from "@/lib/api/types";
import { longDate } from "@/lib/format";

import { SourceLink } from "./SourceLink";

/** Official rules and community rules are always labelled differently (brief §4). */
export function RuleKind({ r }: { r: Pick<ApplicationRule, "source_type" | "verification"> }) {
  if (r.source_type === "community") {
    return <span className="inline-flex rounded-sm bg-unverified-bg px-2 py-0.5 text-xs font-medium text-unverified">Community-reported rule (not published by the bank)</span>;
  }
  if (r.verification === "third_party_quote") {
    return <span className="inline-flex rounded-sm bg-info-bg px-2 py-0.5 text-xs font-medium text-info">Bank rule, quoted by a third party — not yet confirmed on the bank&apos;s page</span>;
  }
  return <span className="inline-flex rounded-sm bg-navy-50 px-2 py-0.5 text-xs font-medium text-navy-900">Official bank rule</span>;
}

export function RuleList({ rules }: { rules: ApplicationRule[] }) {
  if (!rules.length) return <p className="text-sm text-ink-500">No application or bonus rules recorded for this card yet.</p>;
  return (
    <ul className="space-y-3">
      {rules.map((r) => (
        <li key={r.rule_key} className="rounded-md border border-border p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <RuleKind r={r} />
            <span className="text-xs text-ink-500">Affects {r.effect === "approval" ? "approval" : "earning the bonus"}</span>
          </div>
          <p className="mt-1 font-medium text-ink-900">{r.name}</p>
          <blockquote className="mt-1 border-l-2 border-border pl-3 text-ink-700">“{r.excerpt}”</blockquote>
          {r.notes.length ? <ul className="mt-1 list-disc pl-5 text-xs text-ink-500">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
          <p className="mt-1 text-xs text-ink-500"><SourceLink href={r.source_url}>{r.source_title ?? "Source"}</SourceLink> · checked {longDate(r.verified_at)}</p>
        </li>
      ))}
    </ul>
  );
}
