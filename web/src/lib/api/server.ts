import "server-only";

import type { CompareResponse, HistoryEntry, OfferSort, Page, Product, PublicOffers, SourcesResponse } from "./types";

/** Server-side API client. Responses are cached with tags so the pipeline can revalidate them on publish. */
const BASE = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const REVALIDATE_SECONDS = 3600;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function get<T>(path: string, tags: string[]): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, { next: { revalidate: REVALIDATE_SECONDS, tags } });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}`);
  return (await res.json()) as T;
}

export const TYPE_PATH = { credit_card: "credit-cards", checking: "checking-accounts", savings: "savings-accounts" } as const;

export function listProducts(type: keyof typeof TYPE_PATH, params: URLSearchParams): Promise<Page> {
  const qs = params.toString();
  return get<Page>(`/${TYPE_PATH[type]}${qs ? `?${qs}` : ""}`, [`listing:${type}`, "listing:all"]);
}

/** Public offers of Verified products, ranked by a dollar estimate (home page; no user inputs). */
export function getRankedOffers(type: keyof typeof TYPE_PATH, sort: OfferSort, limit = 12): Promise<PublicOffers> {
  return get<PublicOffers>(`/offers/ranked?type=${type}&sort=${sort}&limit=${limit}`, [`listing:${type}`, "listing:all"]);
}

export function getProduct(id: string): Promise<Product> {
  return get<Product>(`/products/${encodeURIComponent(id)}`, [`product:${id}`]);
}

export function getHistory(id: string): Promise<HistoryEntry[]> {
  return get<HistoryEntry[]>(`/products/${encodeURIComponent(id)}/history`, [`product:${id}`]);
}

export function getSources(): Promise<SourcesResponse> {
  return get<SourcesResponse>("/sources", ["sources"]);
}

export function getMethodology(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>("/methodology", ["methodology"]);
}

export async function compare(ids: string[]): Promise<CompareResponse> {
  const res = await fetch(`${BASE}/api/v1/compare`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ product_ids: ids }),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}`);
  return (await res.json()) as CompareResponse;
}
