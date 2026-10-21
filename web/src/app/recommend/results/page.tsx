import type { Metadata } from "next";

import { Results } from "@/components/Results";
import { PageTitle } from "@/components/Site";

export const metadata: Metadata = { title: "Your results", robots: { index: false } };

export default function ResultsPage() {
  return (
    <>
      <PageTitle title="Your recommendations" intro="Step 3 of 3. Each result shows its estimated dollar value, why it fits your answers, and the assumptions behind the estimate." />
      <Results />
    </>
  );
}
