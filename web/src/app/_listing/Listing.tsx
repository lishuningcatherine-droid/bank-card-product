import { FilterBar } from "@/components/FilterBar";
import { ProductCard } from "@/components/ProductCard";
import { PageTitle } from "@/components/Site";
import { EmptyState, ErrorState } from "@/components/States";
import { getSources, listProducts } from "@/lib/api/server";
import type { Page } from "@/lib/api/types";

type SP = Record<string, string | string[] | undefined>;

function toApiParams(sp: SP): { api: URLSearchParams; flat: Record<string, string> } {
  const flat: Record<string, string> = {};
  for (const [k, v] of Object.entries(sp)) if (typeof v === "string" && v) flat[k] = v;
  const flags = Array.isArray(sp.flag) ? sp.flag : sp.flag ? [sp.flag] : [];
  if (flags.length) flat.card_flags = flags.join(",");
  const api = new URLSearchParams();
  for (const k of ["q", "bank", "annual_fee_max", "reward_category", "segment", "apy_min", "has_bonus", "card_flags", "page"]) {
    if (flat[k]) api.set(k, flat[k]!);
  }
  const days = Number(flat.verified_within);
  if (days > 0) api.set("verified_since", new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10) + "T00:00:00Z");
  api.set("page_size", "24");
  return { api, flat };
}

export async function Listing({ type, title, intro, basePath, searchParams }: {
  type: "credit_card" | "checking" | "savings"; title: string; intro: string; basePath: string; searchParams: Promise<SP>;
}) {
  const { api, flat } = toApiParams(await searchParams);
  let page: Page | null = null;
  let banks: { value: string; label: string }[] = [];
  try {
    [page, banks] = await Promise.all([
      listProducts(type, api),
      getSources().then((s) => s.banks.map((b) => ({ value: b.bank_id, label: b.display_name }))),
    ]);
  } catch {
    page = null;
  }
  const filtered = [...api.keys()].some((k) => k !== "page_size");
  return (
    <>
      <PageTitle title={title} intro={intro} />
      <FilterBar type={type} banks={banks} params={flat} basePath={basePath} />
      <section aria-label="Results" className="mt-6">
        {page === null ? (
          <ErrorState>We couldn&apos;t load products right now. Please refresh the page in a moment.</ErrorState>
        ) : page.items.length === 0 ? (
          <EmptyState title={filtered ? "No products match these filters" : "No verified products yet"}
            href={filtered ? basePath : "/sources"} cta={filtered ? "Clear filters" : "See data sources"}>
            {filtered ? "Try removing a filter." : "Products appear only after their official pages are retrieved and verified."}
          </EmptyState>
        ) : (
          <>
            <p className="mb-3 text-sm text-ink-500" aria-live="polite">{page.total} product{page.total === 1 ? "" : "s"}</p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {page.items.map((p) => <ProductCard key={p.id} product={p} />)}
            </div>
          </>
        )}
      </section>
    </>
  );
}
