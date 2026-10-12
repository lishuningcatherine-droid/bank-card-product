import type { Metadata } from "next";
import Link from "next/link";

import { PageTitle } from "@/components/Site";

export const metadata: Metadata = { title: "Get recommendations", description: "Choose a product type to start." };

export default function RecommendStart() {
  const types = [
    ["credit-card", "Credit card", "Rewards, travel, low interest, balance transfer, or building credit."],
    ["checking", "Checking account", "Low fees and bonuses you can actually qualify for."],
    ["savings", "Savings account", "APY for your balance and bonus deposit rules."],
  ] as const;
  return (
    <>
      <PageTitle title="What are you looking for?" intro="Step 1 of 3. You'll answer a few questions using broad ranges — nothing is stored." />
      <ul className="grid gap-4 md:grid-cols-3">
        {types.map(([slug, t, d]) => (
          <li key={slug}>
            <Link href={`/recommend/${slug}`} className="block h-full rounded-lg border border-border p-5 no-underline shadow-card hover:border-border-strong">
              <span className="text-lg font-semibold text-ink-900">{t}</span>
              <span className="mt-1 block text-sm text-ink-700">{d}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
