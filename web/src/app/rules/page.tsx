import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { RuleList } from "@/components/RuleList";
import { ErrorState } from "@/components/States";
import { getRules } from "@/lib/api/server";
import type { ApplicationRule } from "@/lib/api/types";

export const metadata: Metadata = {
  title: "Application and bonus rules",
  description: "Issuer rules on applications and welcome-bonus eligibility, with their sources, kept apart from community-reported rules.",
};

const BANK: Record<string, string> = {
  american_express: "American Express", bank_of_america: "Bank of America", capital_one: "Capital One", chase: "Chase",
  citi: "Citi", discover: "Discover", wells_fargo: "Wells Fargo",
};

export default async function RulesPage() {
  let rules: ApplicationRule[] | null = null;
  try {
    rules = await getRules();
  } catch {
    rules = null;
  }
  const banks = [...new Set((rules ?? []).map((r) => r.bank_id))].sort();
  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-3xl">Application and bonus rules</h1>
        <p className="mt-3 text-ink-700">
          Rules that decide whether you can be approved for a card, and separately whether you can earn its welcome
          bonus. Rules published by a bank are quoted in its own words from its own page. Rules banks do not publish
          but that reliable community sources report are labelled as such and never presented as the bank&apos;s rules.
          Each rule shows its source and when it was last checked.
        </p>
      </header>
      {rules === null ? <ErrorState>We couldn&apos;t load the rules right now.</ErrorState> : banks.map((b) => (
        <section key={b} aria-labelledby={`b-${b}`} className="space-y-3">
          <h2 id={`b-${b}`} className="text-2xl">{BANK[b] ?? b}</h2>
          <RuleList rules={rules!.filter((r) => r.bank_id === b)} />
        </section>
      ))}
      <Disclaimer />
    </div>
  );
}
