"use client";

import { ErrorState } from "@/components/States";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="py-8">
      <h1 className="sr-only">Error</h1>
      <ErrorState retry={reset}>This page couldn&apos;t be loaded. Please try again.</ErrorState>
    </div>
  );
}
