import { createHmac, timingSafeEqual } from "node:crypto";

/** Verifies `X-Bankrec-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, t + "." + body)>` (DESIGN §21.4). */
export const MAX_SKEW_SECONDS = 300;
export const MAX_BODY_BYTES = 4096;
export const MAX_TAGS = 200;
export const TAG_PATTERN =
  /^(product:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|listing:(credit_card|checking|savings|all)|bank:[a-z0-9_]+|sources|methodology)$/;

export function verifySignature(header: string | null, body: string, secret: string, nowSeconds: number): boolean {
  if (!header || !secret || secret.length < 32) return false;
  const parts = Object.fromEntries(header.split(",").map((kv) => kv.trim().split("=", 2) as [string, string]));
  const t = Number(parts.t);
  const v1 = parts.v1;
  if (!Number.isInteger(t) || !v1 || !/^[0-9a-f]{64}$/.test(v1)) return false;
  if (Math.abs(nowSeconds - t) > MAX_SKEW_SECONDS) return false;
  const expected = createHmac("sha256", secret).update(`${t}.`).update(body).digest();
  const given = Buffer.from(v1, "hex");
  return given.length === expected.length && timingSafeEqual(given, expected);
}

export function parseTags(body: string): string[] | null {
  try {
    const parsed = JSON.parse(body) as unknown;
    if (!parsed || typeof parsed !== "object" || !Array.isArray((parsed as { tags?: unknown }).tags)) return null;
    const tags = (parsed as { tags: unknown[] }).tags;
    if (tags.length === 0 || tags.length > MAX_TAGS) return null;
    if (!tags.every((t): t is string => typeof t === "string" && TAG_PATTERN.test(t))) return null;
    return tags;
  } catch {
    return null;
  }
}
