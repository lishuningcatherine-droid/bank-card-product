"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

const KEY = "bankrec.compare";
const MAX = 4;
const listeners = new Set<() => void>();

function read(): string[] {
  try {
    return JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function write(ids: string[]): void {
  window.sessionStorage.setItem(KEY, JSON.stringify(ids));
  listeners.forEach((l) => l());
}

function useSelection(): string[] {
  const snap = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => window.sessionStorage.getItem(KEY) ?? "[]",
    () => "[]",
  );
  return JSON.parse(snap) as string[];
}

export function CompareToggle({ id, name }: { id: string; name: string }) {
  const sel = useSelection();
  const checked = sel.includes(id);
  const full = !checked && sel.length >= MAX;
  return (
    <label className={`inline-flex min-h-11 items-center gap-2 text-sm ${full ? "text-ink-500" : ""}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={full}
        onChange={() => write(checked ? read().filter((x) => x !== id) : [...read(), id].slice(0, MAX))}
        className="h-4 w-4 accent-navy-900"
      />
      Compare<span className="sr-only"> {name}</span>
    </label>
  );
}

export function CompareBar() {
  const sel = useSelection();
  if (sel.length === 0) return null;
  return (
    <div role="region" aria-label="Comparison selection" className="sticky bottom-0 z-20 border-t border-border bg-surface p-3 shadow-raised">
      <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-3 px-4">
        <p className="text-sm">
          {sel.length} of {MAX} selected {sel.length < 2 ? "(choose at least 2)" : ""}
        </p>
        <div className="flex gap-3">
          <button type="button" onClick={() => write([])} className="min-h-11 rounded-md border border-border-strong px-3 text-sm">
            Clear
          </button>
          {sel.length >= 2 ? (
            <Link href={`/compare?ids=${sel.join(",")}`} className="inline-flex min-h-11 items-center rounded-md bg-navy-900 px-4 text-sm font-medium text-white no-underline">
              Compare {sel.length}
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
