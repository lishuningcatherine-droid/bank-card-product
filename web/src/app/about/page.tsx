import type { Metadata } from "next";

import { PageTitle } from "@/components/Site";

export const metadata: Metadata = { title: "About" };

export default function About() {
  return (
    <div className="max-w-3xl space-y-4">
      <PageTitle title="About" />
      <p>This site helps you discover and compare publicly available U.S. credit cards, checking accounts and savings accounts, and get transparent recommendations based on broad information about your needs.</p>
      <p>Every product comes from the bank&apos;s official website. Each value is traced to the text it came from on the official page, and every product shows when it was last checked. When we can&apos;t verify something, we say so instead of guessing.</p>
      <p>We have no affiliate or advertiser relationships. Rankings are not paid, and there are no affiliate links.</p>
      <p>Bank names are shown in plain text. Trademarks belong to their owners.</p>
    </div>
  );
}
