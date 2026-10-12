import "./globals.css";

import type { Metadata } from "next";

import { CompareBar } from "@/components/CompareToggle";
import { SiteFooter, SiteHeader, TestDataBanner } from "@/components/Site";

export const metadata: Metadata = {
  title: { default: "Bank Product Compare — verified U.S. cards and accounts", template: "%s · Bank Product Compare" },
  description:
    "Compare publicly available U.S. credit cards, checking and savings accounts. Every product links to its official source and shows when it was last checked.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-surface text-ink-700 antialiased">
        <TestDataBanner />
        <SiteHeader />
        <main id="main" className="mx-auto max-w-[1200px] px-4 py-8 md:px-6">
          {children}
        </main>
        <CompareBar />
        <SiteFooter />
      </body>
    </html>
  );
}
