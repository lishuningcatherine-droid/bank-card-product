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

/** Rate qualifiers (DESIGN §24.17 A); the stating page words are shown on hover. */
export const CONDITION_LABEL: Record<string, string> = {
  portal_only: "Issuer travel portal only",
  booked_direct: "Only when booked directly",
  partner_only: "Only at the partner",
  us_only: "U.S. purchases only",
  excludes_superstores: "Excludes superstores",
  excludes_warehouse_clubs: "Excludes warehouse clubs",
  enrollment_required: "Enrollment or activation required",
};
/** Qualifiers that keep a rate out of estimates unless the user opts in (or prefers the partner). */
export const RESTRICTIVE = new Set(["portal_only", "booked_direct", "partner_only"]);

export const CATEGORY_LABEL: Record<string, string> = {
  groceries: "Groceries", dining: "Dining", travel: "Travel", travel_portal: "Travel (portal)", airline: "Airline",
  hotel: "Hotel", gas: "Gas", ev_charging: "EV charging", entertainment: "Entertainment", streaming: "Streaming",
  transit: "Transit", online_shopping: "Online shopping", drugstores: "Drugstores", wholesale_clubs: "Wholesale clubs",
  home_improvement: "Home improvement", rotating: "Rotating categories", other: "Everything else",
  online_grocery: "Online grocery", food_delivery: "Food delivery", select_travel: "Select travel",
  office_supply: "Office supply stores", telecom: "Internet, cable & phone", advertising: "Advertising",
  shipping: "Shipping", choice: "Category you choose", choice_everyday: "Everyday category you choose",
  partner: "Partner purchases", merchant: "Specific merchant", foreign_purchases: "Foreign purchases", car_rental: "Car rental",
};

export const TYPE_LABEL = { credit_card: "Credit card", checking: "Checking account", savings: "Savings account" } as const;

export function rateText(rate: string | number, unit: string): string {
  const n = Number(rate);
  return unit === "pct" ? `${n}%` : `${n}x`;
}
