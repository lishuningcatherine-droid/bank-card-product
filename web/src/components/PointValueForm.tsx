import type { PointValue } from "@/lib/api/types";

/** The visitor's own cents-per-point values (GET form: works without JavaScript). Empty = the conservative default. */
export function PointValueForm({ programs, current, action, keep }: { programs: PointValue[]; current: Record<string, string>; action: string; keep: Record<string, string> }) {
  return (
    <details className="rounded-md border border-border p-4 text-sm" open={Object.keys(current).length > 0}>
      <summary className="cursor-pointer font-medium text-ink-900">Value of points and miles (your own assumption)</summary>
      <form method="get" action={action} className="mt-3 space-y-3">
        {Object.entries(keep).map(([k, v]) => <input key={k} type="hidden" name={k} value={v} />)}
        <p className="text-ink-700">By default points count only at a cash value an official page states; programs without one show no dollar figure. Enter cents per point to compare with your own value.</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {programs.map((p) => (
            <label key={p.program} className="flex flex-col font-medium text-ink-900">
              {p.name}
              <span className="text-xs font-normal text-ink-500">Default: {p.floor_cents == null ? "no dollar value" : `${p.floor_cents}¢ (official cash value)`}</span>
              <input type="number" name={`v_${p.program}`} min={0} max={10} step={0.05} defaultValue={current[p.program] ?? ""}
                inputMode="decimal" className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal" />
            </label>
          ))}
        </div>
        <button type="submit" className="inline-flex min-h-11 items-center rounded-md bg-navy-900 px-5 font-medium text-white hover:bg-navy-700">Update values</button>
      </form>
    </details>
  );
}

/** {program: cents} from v_<program> query parameters → "program:cents,…" for the API. */
export function pvFromParams(sp: Record<string, string | string[] | undefined>): { pv: string; values: Record<string, string> } {
  const values: Record<string, string> = {};
  for (const [k, v] of Object.entries(sp)) {
    if (k.startsWith("v_") && typeof v === "string" && /^\d{1,2}(\.\d{1,3})?$/.test(v)) values[k.slice(2)] = v;
  }
  return { pv: Object.entries(values).map(([k, v]) => `${k}:${v}`).join(","), values };
}
