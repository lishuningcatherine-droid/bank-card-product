import type { Result } from "@/lib/api/types";

import { Money } from "./Money";

export function ValueSplit({ result }: { result: Result }) {
  const v = result.values;
  const rows: [string, number | null | undefined, string][] = [
    ["Ongoing annual value", v.ongoing_annual_cents, "Recurring rewards or interest, plus credits you selected, minus recurring fees."],
    ["Promotional value", v.promotional_cents, "One-time bonus, counted only if you can meet the requirement and the amount is exact."],
    ["First-year value", v.first_year_cents, "Ongoing value + promotional value + first-year fee differences."],
  ];
  return (
    <div>
      <dl className="divide-y divide-border rounded-md border border-border">
        {rows.map(([label, cents, hint]) => (
          <div key={label} className="flex items-start justify-between gap-4 p-3">
            <dt>
              <span className="font-medium text-ink-900">{label}</span>
              <span className="block text-xs text-ink-500">{hint}</span>
            </dt>
            <dd className="text-lg font-semibold">
              <Money cents={cents} />
            </dd>
          </div>
        ))}
        {v.non_monetized && v.non_monetized.length ? (
          <div className="p-3">
            <dt className="font-medium text-ink-900">Not given a dollar value</dt>
            <dd className="mt-1 text-sm">{v.non_monetized.join(" · ")}</dd>
          </div>
        ) : null}
      </dl>
      {v.year1_cents != null ? (
        <table className="mt-3 w-full text-sm">
          <caption className="text-left font-medium text-ink-900">Multi-year view</caption>
          <thead>
            <tr className="text-ink-500">
              <th scope="col" className="py-1 text-left font-normal">Year 1</th>
              <th scope="col" className="py-1 text-left font-normal">Year 2</th>
              <th scope="col" className="py-1 text-left font-normal">Year 3</th>
              <th scope="col" className="py-1 text-left font-normal">3-year total</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><Money cents={v.year1_cents} /></td>
              <td><Money cents={v.year2_cents} /></td>
              <td><Money cents={v.year3_cents} /></td>
              <td className="font-semibold"><Money cents={v.three_year_total_cents} /></td>
            </tr>
          </tbody>
        </table>
      ) : null}
      {(v.credits_counted ?? []).length ? (
        <ul className="mt-2 text-sm">
          {(v.credits_counted ?? []).map((c) => (
            <li key={String(c.id)}>
              Credit counted: {String(c.name)} (<Money cents={Number(c.annual_value_cents)} />/year)
            </li>
          ))}
        </ul>
      ) : null}
      {result.break_even ? <p className="mt-2 text-sm">{result.break_even}</p> : null}
    </div>
  );
}
