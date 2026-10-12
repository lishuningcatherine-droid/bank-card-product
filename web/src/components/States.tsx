import Link from "next/link";

export function EmptyState({ title, children, href, cta }: { title: string; children?: React.ReactNode; href?: string; cta?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-subtle p-8 text-center">
      <h2 className="text-lg">{title}</h2>
      {children ? <div className="mx-auto mt-2 max-w-prose text-sm">{children}</div> : null}
      {href && cta ? (
        <Link href={href} className="mt-4 inline-block font-medium underline">
          {cta}
        </Link>
      ) : null}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", children, retry }: { title?: string; children?: React.ReactNode; retry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-expired bg-expired-bg p-6">
      <h2 className="text-lg text-expired">{title}</h2>
      <div className="mt-1 text-sm text-ink-700">{children ?? "We couldn't load this data. Please try again."}</div>
      {retry ? (
        <button type="button" onClick={retry} className="mt-3 min-h-11 rounded-md border border-border-strong bg-surface px-4 font-medium text-ink-900">
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function SkeletonCards({ count = 6 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="h-56 rounded-lg border border-border bg-surface-subtle motion-safe:animate-pulse" />
      ))}
    </div>
  );
}
