import type { RecommendRequest } from "./api/types";

/** Inputs live only in the URL fragment (never sent to any server or analytics) and in memory. */
export function encodeRequest(r: RecommendRequest): string {
  const json = JSON.stringify(r);
  const b64 = typeof window === "undefined" ? Buffer.from(json).toString("base64") : window.btoa(unescape(encodeURIComponent(json)));
  return b64.replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function decodeRequest(hash: string): RecommendRequest | null {
  try {
    const b64 = hash.replace(/^#/, "").replaceAll("-", "+").replaceAll("_", "/");
    if (!b64) return null;
    const json = decodeURIComponent(escape(window.atob(b64)));
    const r = JSON.parse(json) as RecommendRequest;
    return r && ["credit_card", "checking", "savings"].includes(r.product_type) ? r : null;
  } catch {
    return null;
  }
}
