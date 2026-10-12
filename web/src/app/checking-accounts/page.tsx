import type { Metadata } from "next";

import { Listing } from "../_listing/Listing";

export const metadata: Metadata = { title: "Checking accounts", description: "Monthly fees, ways to waive them, and bonuses — with the official source and the date we last checked." };

export default function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Listing type="checking" title="Checking accounts" intro="Monthly fees, ways to waive them, and bonuses — with the official source and the date we last checked." basePath="/checking-accounts" searchParams={searchParams} />;
}
