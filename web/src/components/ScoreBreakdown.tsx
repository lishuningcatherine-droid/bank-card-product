import type { Result } from "@/lib/api/types";

export function ScoreBreakdown({ result }: { result: Result }) {
  const max = Math.max(...result.components.map((c) => c.contribution), 1);
  return (
    <details className="rounded-md border border-border p-3">
      <summary className="cursor-pointer font-medium text-ink-900">
        Score <span className="tabular">{result.score.toFixed(1)}</span> of 100 — see how it was calculated
      </summary>
      <ul className="mt-3 space-y-2">
        {result.components.map((c) => (
          <li key={c.key} className="text-sm">
            <div className="flex justify-between">
              <span>{c.label}</span>
              <span className="tabular text-ink-500">{c.contribution.toFixed(1)} pts</span>
            </div>
            <div role="img" aria-label={`${c.label}: ${c.contribution.toFixed(1)} points`} className="mt-1 h-2 rounded-sm bg-surface-subtle">
              <div className="h-2 rounded-sm bg-navy-700" style={{ width: `${(c.contribution / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
