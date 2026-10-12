import type { Metadata } from "next";

import { Listing } from "../_listing/Listing";

export const metadata: Metadata = { title: "Savings accounts", description: "APY (by balance tier where it applies), fees, and bonus rules. APYs are variable." };

export default function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Listing type="savings" title="Savings accounts" intro="APY (by balance tier where it applies), fees, and bonus rules. APYs are variable." basePath="/savings-accounts" searchParams={searchParams} />;
}
