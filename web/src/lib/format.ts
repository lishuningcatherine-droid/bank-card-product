/** Formatting helpers. All money arrives as integer cents; rates as percentage strings/numbers. */

export function usd(cents: number | null | undefined, opts: { signed?: boolean } = {}): string {
  if (cents === null || cents === undefined) return "—";
  const neg = cents < 0;
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100).toLocaleString("en-US");
  const frac = abs % 100;
  const s = `$${whole}${frac ? `.${String(frac).padStart(2, "0")}` : ""}`;
  return neg ? `−${s}` : opts.signed && cents > 0 ? `+${s}` : s;
}

export function pct(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return "—";
  return `${n.toLocaleString("en-US", { maximumFractionDigits: 3 })}%`;
}

export function aprRange(min: unknown, max: unknown): string | null {
  if (min === null || min === undefined) return null;
  return min === max || max === null || max === undefined ? pct(min as string) : `${pct(min as string)}–${pct(max as string)}`;
}

export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export function relativeHours(iso: string, now: Date = new Date()): string {
  const ms = now.getTime() - new Date(iso).getTime();
  const h = Math.max(0, Math.round(ms / 3_600_000));
  if (h < 1) return "less than an hour ago";
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} days ago`;
}

export const CATEGORY_LABEL: Record<string, string> = {
  groceries: "Groceries", dining: "Dining", travel: "Travel", travel_portal: "Travel (portal)", airline: "Airline",
  hotel: "Hotel", gas: "Gas", ev_charging: "EV charging", entertainment: "Entertainment", streaming: "Streaming",
  transit: "Transit", online_shopping: "Online shopping", drugstores: "Drugstores", wholesale_clubs: "Wholesale clubs",
  home_improvement: "Home improvement", rotating: "Rotating categories", other: "Everything else",
  online_grocery: "Online grocery", food_delivery: "Food delivery", select_travel: "Select travel",
};

export const TYPE_LABEL = { credit_card: "Credit card", checking: "Checking account", savings: "Savings account" } as const;

export function rateText(rate: string | number, unit: string): string {
  const n = Number(rate);
  return unit === "pct" ? `${n}%` : `${n}x`;
}
