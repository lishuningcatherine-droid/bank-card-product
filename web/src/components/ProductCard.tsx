import Link from "next/link";

import type { Product } from "@/lib/api/types";

import { CheckedAgo } from "./CheckedAgo";
import { CompareToggle } from "./CompareToggle";
import { OfferBlock } from "./OfferBlock";
import { keyFacts } from "./ProductFacts";
import { StatusLabel } from "./StatusLabel";
import { VerificationBadge } from "./VerificationBadge";

export function ProductCard({ product }: { product: Product }) {
  const offer = product.offers?.[0];
  return (
    <article className="flex flex-col rounded-lg border border-border bg-surface p-5 shadow-card">
      <p className="text-sm text-ink-500">{product.bank_name}</p>
      <h3 className="mt-0.5 text-lg leading-snug">
        <Link href={`/products/${product.id}`} className="text-ink-900 no-underline hover:underline">
          {product.name}
        </Link>
      </h3>
      <div className="mt-2 flex flex-wrap gap-2">
        <VerificationBadge product={product} />
        {product.recheck_pending ? <StatusLabel status="recheck" /> : null}
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-1 text-sm">
        {keyFacts(product).map((f) => (
          <div key={f.label} className="flex justify-between gap-3">
            <dt className="text-ink-500">{f.label}</dt>
            <dd className="text-right text-ink-900">{f.value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3">{offer ? <OfferBlock offer={offer} compact /> : null}</div>
      <div className="mt-auto pt-3">
        <CheckedAgo checkedAt={product.last_checked_at} changedAt={product.last_changed_at} />
        <div className="mt-3 flex items-center justify-between">
          <Link href={`/products/${product.id}`} className="font-medium">
            Details<span className="sr-only"> for {product.name}</span>
          </Link>
          <CompareToggle id={product.id} name={product.name} />
        </div>
      </div>
    </article>
  );
}
