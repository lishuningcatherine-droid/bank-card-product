import { useId } from "react";

export function NumberField({ label, name, value, onChange, hint, min = 0, max, prefix = "$", error }: {
  label: string; name: string; value: number; onChange: (v: number) => void; hint?: string; min?: number; max?: number;
  prefix?: string; error?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col">
      <label htmlFor={id} className="text-sm font-medium text-ink-900">{label}</label>
      {hint ? <span id={`${id}-hint`} className="text-xs text-ink-500">{hint}</span> : null}
      <div className="mt-1 flex items-center rounded-md border border-border-strong bg-surface focus-within:outline-2 focus-within:outline-focus">
        {prefix ? <span className="pl-3 text-ink-500" aria-hidden="true">{prefix}</span> : null}
        <input id={id} name={name} type="number" inputMode="numeric" min={min} max={max} value={Number.isFinite(value) ? value : ""}
          aria-invalid={error ? true : undefined}
          aria-describedby={[hint ? `${id}-hint` : "", error ? `${id}-err` : ""].filter(Boolean).join(" ") || undefined}
          onChange={(e) => onChange(Math.max(min, Math.min(max ?? Number.MAX_SAFE_INTEGER, Math.round(Number(e.target.value) || 0))))}
          className="min-h-11 w-full rounded-md bg-transparent px-3 tabular outline-none" />
      </div>
      {error ? <span id={`${id}-err`} className="mt-1 text-xs text-expired">{error}</span> : null}
    </div>
  );
}

export function Choice<T extends string>({ legend, name, value, options, onChange, hint }: {
  legend: string; name: string; value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; hint?: string;
}) {
  return (
    <fieldset>
      <legend className="text-sm font-medium text-ink-900">{legend}</legend>
      {hint ? <p className="text-xs text-ink-500">{hint}</p> : null}
      <div className="mt-1 flex flex-wrap gap-2">
        {options.map(([v, l]) => (
          <label key={v} className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm ${value === v ? "border-navy-900 bg-navy-50 text-navy-900" : "border-border-strong"}`}>
            <input type="radio" name={name} value={v} checked={value === v} onChange={() => onChange(v)} className="accent-navy-900" />
            {l}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="inline-flex min-h-11 items-start gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-4 w-4 accent-navy-900" />
      <span><span className="font-medium text-ink-900">{label}</span>{hint ? <span className="block text-xs text-ink-500">{hint}</span> : null}</span>
    </label>
  );
}

export const STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"] as const;
