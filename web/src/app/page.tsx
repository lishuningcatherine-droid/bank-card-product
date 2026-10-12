import Link from "next/link";

const STEPS = [
  ["1", "Choose a product type", "Credit cards, checking accounts, or savings accounts."],
  ["2", "Tell us your needs", "Broad ranges only. Nothing you enter is stored."],
  ["3", "Compare verified recommendations", "Each result explains its score and links to the official page."],
] as const;

const TYPES = [
  ["/credit-cards", "Credit cards", "Consumer, business, co-branded, student and secured cards."],
  ["/checking-accounts", "Checking accounts", "Monthly fees, waivers, and bonuses you can actually reach."],
  ["/savings-accounts", "Savings accounts", "APY by balance, fees, and bonus deposit rules."],
] as const;

export default function Home() {
  return (
    <div className="space-y-12">
      <section className="max-w-3xl">
        <h1 className="text-4xl leading-tight">Compare U.S. bank products with the sources in plain sight</h1>
        <p className="mt-4 text-lg">
          Recommendations are deterministic and explained line by line. Every product links to the bank&apos;s official
          page and shows when we last checked it.
        </p>
        <Link href="/recommend" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-navy-900 px-6 font-medium text-white no-underline hover:bg-navy-700">
          Get recommendations
        </Link>
      </section>
      <section aria-labelledby="how">
        <h2 id="how" className="text-2xl">How it works</h2>
        <ol className="mt-4 grid gap-4 md:grid-cols-3">
          {STEPS.map(([n, t, d]) => (
            <li key={n} className="rounded-lg border border-border p-5">
              <span className="tabular text-sm font-semibold text-navy-700">Step {n}</span>
              <h3 className="mt-1 text-lg">{t}</h3>
              <p className="mt-1 text-sm">{d}</p>
            </li>
          ))}
        </ol>
      </section>
      <section aria-labelledby="browse">
        <h2 id="browse" className="text-2xl">Browse by product type</h2>
        <ul className="mt-4 grid gap-4 md:grid-cols-3">
          {TYPES.map(([href, t, d]) => (
            <li key={href}>
              <Link href={href} className="block h-full rounded-lg border border-border bg-surface p-5 no-underline shadow-card hover:border-border-strong">
                <span className="text-lg font-semibold text-ink-900">{t}</span>
                <span className="mt-1 block text-sm text-ink-700">{d}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
