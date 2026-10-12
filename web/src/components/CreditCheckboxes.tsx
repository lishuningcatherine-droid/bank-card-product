"use client";

import type { Product } from "@/lib/api/types";
import { usd } from "@/lib/format";

export function CreditCheckboxes({ products, selected, onChange }: { products: Product[]; selected: string[]; onChange: (ids: string[]) => void }) {
  const credits = products.flatMap((p) => (p.benefits ?? []).filter((b) => b.monetizable && b.annual_value_cents).map((b) => ({ ...b, product: p.name })));
  if (!credits.length) return null;
  return (
    <fieldset className="rounded-md border border-border p-3">
      <legend className="px-1 font-medium text-ink-900">Statement credits you would actually use</legend>
      <p className="text-xs text-ink-500">Unchecked credits are not counted in any value.</p>
      <div className="mt-2 grid gap-1">
        {credits.map((c) => (
          <label key={c.id} className="inline-flex min-h-11 items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-navy-900" checked={selected.includes(c.id)}
              onChange={(e) => onChange(e.target.checked ? [...selected, c.id] : selected.filter((x) => x !== c.id))} />
            {c.name} — <span className="tabular">{usd(c.annual_value_cents)}</span>/year ({c.product})
          </label>
        ))}
      </div>
    </fieldset>
  );
}
