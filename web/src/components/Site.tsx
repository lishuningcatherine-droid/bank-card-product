import Link from "next/link";

import { Disclaimer } from "./Disclaimer";

const NAV = [
  ["/credit-cards", "Credit cards"],
  ["/checking-accounts", "Checking"],
  ["/savings-accounts", "Savings"],
  ["/recommend", "Get recommendations"],
  ["/methodology", "Methodology"],
] as const;

export function SiteHeader() {
  return (
    <header className="bg-navy-900 text-white">
      <a href="#main" className="sr-only-focusable absolute left-2 top-2 rounded-md bg-surface px-3 py-2 text-navy-900">
        Skip to content
      </a>
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-4 py-4 md:px-6">
        <Link href="/" className="text-lg font-semibold text-white no-underline">
          Bank Product Compare
        </Link>
        <nav aria-label="Main">
          <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {NAV.map(([href, label]) => (
              <li key={href}>
                <Link href={href} className="text-white no-underline hover:underline">
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border bg-surface-subtle">
      <div className="mx-auto grid max-w-[1200px] gap-6 px-4 py-8 md:grid-cols-[2fr_1fr] md:px-6">
        <Disclaimer compact />
        <nav aria-label="Footer">
          <ul className="space-y-1 text-sm">
            {[["/sources", "Data sources"], ["/methodology", "Methodology"], ["/about", "About"], ["/privacy", "Privacy"], ["/disclaimer", "Disclaimer"]].map(([h, l]) => (
              <li key={h}><Link href={h!}>{l}</Link></li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  );
}

export function TestDataBanner() {
  if (process.env.NEXT_PUBLIC_TEST_DATA_BANNER !== "1") return null;
  return (
    <div role="note" className="bg-warning-bg px-4 py-2 text-center text-sm text-warning">
      Test data: products shown are from the fictional &ldquo;Example Bank&rdquo; and do not exist.
    </div>
  );
}

export function PageTitle({ title, intro }: { title: string; intro?: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-3xl">{title}</h1>
      {intro ? <div className="mt-2 max-w-3xl text-ink-700">{intro}</div> : null}
    </div>
  );
}
