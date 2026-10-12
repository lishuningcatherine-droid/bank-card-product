export const DISCLAIMER_LINES = [
  "Not financial advice.",
  "Terms change. Confirm all details on the official bank website before applying.",
  "Data is checked on a schedule and is not real-time; each product shows when it was last checked.",
  "We have no affiliate or advertiser relationships, and rankings are not paid.",
];

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  return (
    <aside aria-label="Disclaimer" className={compact ? "text-sm text-ink-500" : "rounded-lg border border-border bg-surface-subtle p-4 text-sm text-ink-700"}>
      <p className="font-medium text-ink-900">Important</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {DISCLAIMER_LINES.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </aside>
  );
}
