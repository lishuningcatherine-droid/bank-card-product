import { usd } from "@/lib/format";

export function Money({ cents, signed = false, tone = "auto" }: { cents: number | null | undefined; signed?: boolean; tone?: "auto" | "plain" }) {
  const positive = tone === "auto" && cents != null && cents > 0;
  return <span className={`tabular ${positive ? "text-positive" : ""}`}>{usd(cents, { signed })}</span>;
}
