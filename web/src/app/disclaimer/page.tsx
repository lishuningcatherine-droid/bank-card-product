import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { PageTitle } from "@/components/Site";

export const metadata: Metadata = { title: "Disclaimer" };

export default function DisclaimerPage() {
  return (
    <div className="max-w-3xl space-y-4">
      <PageTitle title="Disclaimer" />
      <Disclaimer />
      <p>Estimates depend on the inputs you provide and on the assumptions shown with each result (for example the value of a point). Actual rewards, interest and fees depend on the bank&apos;s terms and your use of the product. Welcome offers can vary, can be targeted, and can end at any time.</p>
    </div>
  );
}
