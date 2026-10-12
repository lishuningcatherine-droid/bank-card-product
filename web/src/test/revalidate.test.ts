import { createHmac } from "node:crypto";

import { parseTags, verifySignature } from "@/lib/signature";

const SECRET = "x".repeat(32);
const sign = (body: string, t: number, secret = SECRET) =>
  `t=${t},v1=${createHmac("sha256", secret).update(`${t}.`).update(body).digest("hex")}`;

vi.mock("next/cache", () => ({ revalidateTag: vi.fn() }));

describe("signature", () => {
  const body = JSON.stringify({ tags: ["listing:all", "product:0b7e4c5e-1d2a-4f00-8a00-000000000001"] });
  const now = 1_800_000_000;
  it("accepts a valid signature", () => expect(verifySignature(sign(body, now), body, SECRET, now)).toBe(true));
  it("rejects a bad signature", () => expect(verifySignature(sign(body, now, "y".repeat(32)), body, SECRET, now)).toBe(false));
  it("rejects clock skew", () => expect(verifySignature(sign(body, now - 301), body, SECRET, now)).toBe(false));
  it("rejects a tampered body", () => expect(verifySignature(sign(body, now), body + " ", SECRET, now)).toBe(false));
  it("rejects missing/short secrets", () => expect(verifySignature(sign(body, now, "short"), body, "short", now)).toBe(false));
  it("validates tags", () => {
    expect(parseTags(body)).toHaveLength(2);
    expect(parseTags(JSON.stringify({ tags: ["../../etc"] }))).toBeNull();
    expect(parseTags(JSON.stringify({ tags: [] }))).toBeNull();
    expect(parseTags(JSON.stringify({ tags: Array(201).fill("sources") }))).toBeNull();
    expect(parseTags("not json")).toBeNull();
  });
});

describe("revalidate route", () => {
  it("revalidates on a valid request and returns 404 otherwise", async () => {
    process.env.REVALIDATE_SECRET = SECRET;
    const { POST, GET } = await import("@/app/api/internal/revalidate/route");
    const { revalidateTag } = await import("next/cache");
    const body = JSON.stringify({ tags: ["listing:credit_card", "sources"] });
    const t = Math.floor(Date.now() / 1000);
    const ok = await POST(new Request("http://x/api/internal/revalidate", { method: "POST", body,
      headers: { "content-length": String(body.length), "x-bankrec-signature": sign(body, t) } }));
    expect(ok.status).toBe(200);
    expect(revalidateTag).toHaveBeenCalledWith("listing:credit_card", { expire: 0 });
    const bad = await POST(new Request("http://x/api/internal/revalidate", { method: "POST", body,
      headers: { "content-length": String(body.length), "x-bankrec-signature": "t=1,v1=00" } }));
    expect(bad.status).toBe(404);
    const big = "x".repeat(5000);
    const tooBig = await POST(new Request("http://x", { method: "POST", body: big, headers: { "content-length": "5000", "x-bankrec-signature": sign(big, t) } }));
    expect(tooBig.status).toBe(404);
    expect(GET().status).toBe(404);
  });
});
