import { vi } from "vitest";

const ev = { event: "results_shown" as const, list_id: "l1", product_type: "credit_card", shown: ["a", "b"], ranker: "baseline" };

async function fresh(enabled: boolean) {
  vi.resetModules();
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (url.endsWith("/events/config") ? { enabled, retention_days: 180, stored: [], never_stored: [] } : { deleted: 3 }),
  }));
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
  const mod = await import("@/lib/ranking-events");
  return { mod, fetchMock };
}

const sent = (m: ReturnType<typeof vi.fn>) => m.mock.calls.filter(([u]) => String(u).endsWith("/api/v1/events"));

describe("ranking events are opt-in (DESIGN §26.7)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends nothing before the visitor opts in, even when logging is enabled", async () => {
    const { mod, fetchMock } = await fresh(true);
    await mod.track(ev);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends nothing when the operator has logging off, even after an opt-in", async () => {
    const { mod, fetchMock } = await fresh(false);
    mod.optIn();
    await mod.track(ev);
    expect(sent(fetchMock)).toHaveLength(0);
  });

  it("after an opt-in sends only the event fields with the anonymous id; delete forgets the id", async () => {
    const { mod, fetchMock } = await fresh(true);
    const id = mod.optIn();
    await mod.track(ev);
    const [[, init]] = sent(fetchMock) as [[string, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ consent: true, anon_id: id, ...ev });
    expect(await mod.deleteMyData()).toBe(3);
    expect(mod.anonId()).toBeNull();
  });
});
