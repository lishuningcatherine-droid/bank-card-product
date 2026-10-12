import Link from "next/link";

import { CATEGORY_LABEL } from "@/lib/format";

type Opt = { value: string; label: string };

function Select({ name, label, options, value }: { name: string; label: string; options: Opt[]; value?: string }) {
  return (
    <label className="flex flex-col text-sm font-medium text-ink-900">
      {label}
      <select name={name} defaultValue={value ?? ""} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal text-ink-900">
        <option value="">Any</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** GET form: works without JavaScript; filters live in the URL. */
export function FilterBar({ type, banks, params, basePath }: { type: "credit_card" | "checking" | "savings"; banks: Opt[]; params: Record<string, string>; basePath: string }) {
  const flags = (params.card_flags ?? "").split(",");
  return (
    <form method="get" action={basePath} aria-label="Filters" className="rounded-lg border border-border bg-surface-subtle p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col text-sm font-medium text-ink-900">
          Search
          <input name="q" type="search" defaultValue={params.q ?? ""} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal" />
        </label>
        <Select name="bank" label="Bank" options={banks} value={params.bank} />
        {type === "credit_card" ? (
          <>
            <Select name="annual_fee_max" label="Maximum annual fee" value={params.annual_fee_max}
              options={[{ value: "0", label: "No annual fee" }, { value: "100", label: "Up to $100" }, { value: "250", label: "Up to $250" }, { value: "700", label: "Up to $700" }]} />
            <Select name="reward_category" label="Reward category" value={params.reward_category}
              options={Object.entries(CATEGORY_LABEL).filter(([k]) => k !== "other" && k !== "travel_portal").map(([value, label]) => ({ value, label }))} />
            <Select name="segment" label="Consumer or business" value={params.segment}
              options={[{ value: "consumer", label: "Consumer" }, { value: "business", label: "Business" }]} />
            <fieldset className="text-sm sm:col-span-2">
              <legend className="font-medium text-ink-900">Card type</legend>
              <div className="mt-1 flex flex-wrap gap-x-4">
                {[["co_branded", "Co-branded"], ["student", "Student"], ["secured", "Secured"]].map(([v, l]) => (
                  <label key={v} className="inline-flex min-h-11 items-center gap-2">
                    <input type="checkbox" name="flag" value={v} defaultChecked={flags.includes(v!)} className="h-4 w-4 accent-navy-900" />
                    {l}
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        ) : null}
        {type === "savings" ? (
          <Select name="apy_min" label="Minimum APY" value={params.apy_min}
            options={[{ value: "1", label: "1% or more" }, { value: "3", label: "3% or more" }, { value: "4", label: "4% or more" }]} />
        ) : null}
        <Select name="verified_within" label="Verified within" value={params.verified_within}
          options={[{ value: "7", label: "Last 7 days" }, { value: "30", label: "Last 30 days" }]} />
        <label className="inline-flex min-h-11 items-center gap-2 self-end text-sm">
          <input type="checkbox" name="has_bonus" value="true" defaultChecked={params.has_bonus === "true"} className="h-4 w-4 accent-navy-900" />
          Has a current bonus
        </label>
      </div>
      <div className="mt-4 flex gap-3">
        <button type="submit" className="min-h-11 rounded-md bg-navy-900 px-5 font-medium text-white">
          Apply filters
        </button>
        <Link href={basePath} className="inline-flex min-h-11 items-center px-2 text-sm">
          Clear filters
        </Link>
      </div>
    </form>
  );
}
