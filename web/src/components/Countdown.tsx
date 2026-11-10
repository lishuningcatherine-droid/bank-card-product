"use client";

import { useSyncExternalStore } from "react";

function subscribe(cb: () => void): () => void {
  const t = setInterval(cb, 60_000);
  return () => clearInterval(t);
}
const minuteNow = () => Math.floor(Date.now() / 60_000) * 60_000;

/** Shown only when the issuer stated the date, the time and its zone (the API sends ``countdown_to`` only then). */
export function Countdown({ to }: { to: string }) {
  const now = useSyncExternalStore(subscribe, minuteNow, () => null);
  if (now === null) return null;
  const ms = new Date(to).getTime() - now;
  if (ms <= 0) return <span className="text-xs text-expired">Deadline passed</span>;
  const d = Math.floor(ms / 86_400_000);
  const h = Math.floor((ms % 86_400_000) / 3_600_000);
  return <span className="tabular text-xs text-ink-700">{d > 0 ? `${d} day${d === 1 ? "" : "s"} ` : ""}{h} hour{h === 1 ? "" : "s"} left</span>;
}
