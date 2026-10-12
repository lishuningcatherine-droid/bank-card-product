import { revalidateTag } from "next/cache";

import { MAX_BODY_BYTES, parseTags, verifySignature } from "@/lib/signature";

export const dynamic = "force-dynamic";

const notFound = () => new Response("Not Found", { status: 404, headers: { "cache-control": "no-store" } });

/** Signed on-demand revalidation for the ingestion worker. Any failure returns 404 (not discoverable). */
export async function POST(request: Request): Promise<Response> {
  const secret = process.env.REVALIDATE_SECRET ?? "";
  const length = Number(request.headers.get("content-length") ?? "NaN");
  if (!Number.isFinite(length) || length > MAX_BODY_BYTES) return notFound();
  const body = await request.text();
  if (body.length > MAX_BODY_BYTES) return notFound();
  if (!verifySignature(request.headers.get("x-bankrec-signature"), body, secret, Math.floor(Date.now() / 1000))) {
    return notFound();
  }
  const tags = parseTags(body);
  if (!tags) return notFound();
  // { expire: 0 }: stale pages are never served after a publish; the next visit re-renders with fresh data.
  for (const tag of tags) revalidateTag(tag, { expire: 0 });
  return Response.json({ revalidated: tags.length }, { headers: { "cache-control": "no-store" } });
}

export function GET(): Response {
  return notFound();
}
