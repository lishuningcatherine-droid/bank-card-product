import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Quiz } from "@/components/Quiz";
import { PageTitle } from "@/components/Site";

const TITLES = { "credit-card": "Credit card", checking: "Checking account", savings: "Savings account" } as const;

export function generateStaticParams() {
  return Object.keys(TITLES).map((type) => ({ type }));
}

export async function generateMetadata({ params }: { params: Promise<{ type: string }> }): Promise<Metadata> {
  const t = (await params).type as keyof typeof TITLES;
  return { title: `${TITLES[t] ?? "Recommendation"} questions` };
}

export default async function QuizPage({ params }: { params: Promise<{ type: string }> }) {
  const t = (await params).type;
  if (!(t in TITLES)) notFound();
  return (
    <>
      <PageTitle title={`${TITLES[t as keyof typeof TITLES]}: tell us your needs`}
        intro="Step 2 of 3. Use rough amounts. Your answers stay in this browser tab and are only sent to calculate results — never stored or logged." />
      <Quiz type={t as keyof typeof TITLES} />
    </>
  );
}
