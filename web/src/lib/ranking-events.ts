/** Consented, anonymous ranking events (DESIGN §26.7). Off by default: nothing is sent unless the operator enabled
 * logging AND this visitor opted in. The opt-in lives only in this browser (a random id, no cookie); opting out stops
 * sending, and "delete my data" removes everything recorded under the id from the server. Questionnaire answers are
 * never sent here. */

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const KEY = "bankrec.ranking-events.v1";

export type EventConfig = { enabled: boolean; retention_days: number; stored: string[]; never_stored: string[] };
export type RankingEvent =
  | { event: "results_shown"; list_id: string; product_type: string; shown: string[]; ranker: string }
  | { event: "result_opened" | "official_link_clicked" | "compare_added"; list_id: string; product_type: string; product_id: string; position: number; ranker: string };

let config: Promise<EventConfig | null> | null = null;

export function getEventConfig(): Promise<EventConfig | null> {
  config ??= fetch(`${API}/api/v1/events/config`, { cache: "no-store" })
    .then((r) => (r.ok ? (r.json() as Promise<EventConfig>) : null))
    .catch(() => null);
  return config;
}

export function anonId(): string | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v ? (JSON.parse(v) as { anon_id: string }).anon_id : null;
  } catch {
    return null;
  }
}

export function optIn(): string | null {
  try {
    const id = crypto.randomUUID();
    window.localStorage.setItem(KEY, JSON.stringify({ anon_id: id }));
    return id;
  } catch {
    return null;
  }
}

export function optOut(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: nothing was stored */
  }
}

/** Deletes everything recorded under this browser's id, then forgets the id. */
export async function deleteMyData(): Promise<number | null> {
  const id = anonId();
  if (!id) return 0;
  const res = await fetch(`${API}/api/v1/events/delete`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ anon_id: id }),
  }).catch(() => null);
  if (!res?.ok) return null;
  optOut();
  return ((await res.json()) as { deleted: number }).deleted;
}

export function newListId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : "";
}

/** Sends one event only when logging is enabled and the visitor opted in; silently does nothing otherwise. */
export async function track(e: RankingEvent): Promise<void> {
  const id = anonId();
  if (!id || !e.list_id) return;
  const cfg = await getEventConfig();
  if (!cfg?.enabled) return;
  await fetch(`${API}/api/v1/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ consent: true, anon_id: id, ...e }),
    keepalive: true,
  }).catch(() => undefined);
}
