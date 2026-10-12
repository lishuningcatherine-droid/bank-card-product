import type { Metadata } from "next";

import { Listing } from "../_listing/Listing";

export const metadata: Metadata = { title: "Credit cards", description: "Consumer, business, co-branded, student and secured cards from the banks we cover. Only published products appear, each with its verification status." };

export default function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Listing type="credit_card" title="Credit cards" intro="Consumer, business, co-branded, student and secured cards from the banks we cover. Only published products appear, each with its verification status." basePath="/credit-cards" searchParams={searchParams} />;
}
