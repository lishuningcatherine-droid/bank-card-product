import type { Metadata } from "next";

import { EventConsent } from "@/components/EventConsent";
import { PageTitle } from "@/components/Site";

export const metadata: Metadata = { title: "Privacy" };

export default function Privacy() {
  return (
    <div className="max-w-3xl space-y-4">
      <PageTitle title="Privacy" />
      <ul className="list-disc space-y-2 pl-5">
        <li>We never ask for account numbers, login credentials, Social Security numbers, exact balances, transactions, date of birth or other identity information, and we do not connect to bank accounts.</li>
        <li>The questions use broad, approximate amounts. Your answers stay in your browser tab (in the page address after the <code>#</code>, which browsers do not send to servers) and are sent only to calculate your results.</li>
        <li>Recommendation and comparison inputs are processed and discarded. They are not stored, not logged and not used for analytics.</li>
        <li>We do not use advertising trackers or third-party analytics. Server logs record only technical details such as the page requested and response time.</li>
        <li>Anonymous ranking events are off by default. Only if you turn them on (below or on the results page) do we record which results were shown to you and which you opened, under a random id kept in your browser — never your answers. You can turn this off or delete everything recorded at any time.</li>
        <li>The compare list you build is kept in your browser&apos;s session storage and is cleared when you close the tab.</li>
      </ul>
      <EventConsent detailed />
    </div>
  );
}
