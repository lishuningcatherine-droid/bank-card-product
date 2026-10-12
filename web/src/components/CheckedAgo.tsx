"use client";

import { useEffect, useState } from "react";

import { longDate, relativeHours } from "@/lib/format";

/** Server renders the absolute date; the browser upgrades it to "Checked X hours ago" (never stale in a cached page). */
export function CheckedAgo({ checkedAt, changedAt }: { checkedAt: string; changedAt?: string | null }) {
  const [rel, setRel] = useState<string | null>(null);
  useEffect(() => {
    const update = () => setRel(relativeHours(checkedAt));
    update();
    const t = window.setInterval(update, 60_000);
    return () => window.clearInterval(t);
  }, [checkedAt]);
  return (
    <p className="text-xs text-ink-500">
      <span>
        Checked <time dateTime={checkedAt}>{rel ?? `on ${longDate(checkedAt)}`}</time>
      </span>
      {changedAt ? (
        <span>
          {" "}· Changed on <time dateTime={changedAt}>{longDate(changedAt)}</time>
        </span>
      ) : null}
    </p>
  );
}
