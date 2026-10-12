import type { Product } from "@/lib/api/types";

export function VerificationBadge({ product }: { product: Pick<Product, "label" | "label_reasons"> }) {
  if (product.label === "verified") {
    return (
      <span className="inline-flex items-center rounded-sm bg-navy-50 px-2 py-0.5 text-xs font-medium text-navy-900">
        Verified
      </span>
    );
  }
  return (
    <details className="inline-block text-xs">
      <summary className="cursor-pointer list-none rounded-sm bg-unverified-bg px-2 py-0.5 font-medium text-unverified">
        Partially verified <span className="underline">What&apos;s missing?</span>
      </summary>
      <ul className="mt-1 list-disc pl-5 text-ink-700">
        {(product.label_reasons ?? []).map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </details>
  );
}
