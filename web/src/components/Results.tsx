"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import type { CardRequest, RecommendRequest, RecommendResponse, Result } from "@/lib/api/types";
import { longDate } from "@/lib/format";
import { newListId, track } from "@/lib/ranking-events";
import { decodeRequest, encodeRequest } from "@/lib/request-hash";

import { CreditCheckboxes } from "./CreditCheckboxes";
import { Disclaimer } from "./Disclaimer";
import { EventConsent } from "./EventConsent";
import { OfferBlock } from "./OfferBlock";
import { SourceLink } from "./SourceLink";
import { EmptyState, ErrorState, SkeletonCards } from "./States";
import { ValueSplit } from "./ValueSplit";
import { VerificationBadge } from "./VerificationBadge";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "missing" } | { kind: "ok"; data: RecommendResponse };

type Clicked = (r: Result, event: "result_opened" | "official_link_clicked") => void;

function ResultCard({ r, onClick }: { r: Result; onClick: Clicked }) {
  const p = r.product;
  return (
    <article className="rounded-lg border border-border bg-surface p-5 shadow-card" aria-labelledby={`r-${p.id}`}>
      <div>
        <p className="text-sm text-ink-500">#{r.rank} · {p.bank_name}</p>
        <h2 id={`r-${p.id}`} className="text-xl"><Link href={`/products/${p.id}`} onClick={() => onClick(r, "result_opened")}>{p.name}</Link></h2>
        <div className="mt-1 flex flex-wrap gap-2"><VerificationBadge product={p} /></div>
      </div>
      <p className="mt-2 text-sm font-medium text-ink-900">{r.fee_text}</p>
      {r.over_budget_note ? <p className="mt-1 text-sm text-warning">{r.over_budget_note}</p> : null}
      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <div><ValueSplit result={r} /></div>
        <div className="space-y-4">
          <section aria-label="Why this matches you">
            <h3 className="text-base">Why this matches you</h3>
            <ul className="mt-1 list-disc pl-5 text-sm">{(r.why ?? []).map((w) => <li key={w.code + w.text}>{w.text}</li>)}</ul>
          </section>
          {r.top_features && r.top_features.length ? <p className="text-sm">Top matching categories: {r.top_features.join(", ")}</p> : null}
          {r.current_offer ? <div className="rounded-md border border-border p-3"><OfferBlock offer={r.current_offer} /></div> : null}
          {r.possible_welcome_offer ? <p className="rounded-md bg-info-bg p-3 text-sm text-info">{r.possible_welcome_offer}</p> : null}
          {r.offer_note && !r.current_offer ? <p className="text-sm text-ink-500">{r.offer_note}</p> : null}
          {r.achievability ? (
            <p className="text-sm"><span className="font-medium text-ink-900">Requirement achievable: {r.achievability.achievable ? "yes" : "no"}</span>{" "}— {r.achievability.explanation.replace(/^(Yes|No):\s*/, "")}</p>
          ) : null}
          {r.limitations && r.limitations.length ? (
            <section aria-label="Limitations"><h3 className="text-base">Limitations</h3><ul className="mt-1 list-disc pl-5 text-sm">{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul></section>
          ) : null}
          {r.assumptions && r.assumptions.length ? <p className="text-xs text-ink-500">Assumptions: {r.assumptions.join(" ")}</p> : null}
          <p className="text-xs text-ink-500">Verified {longDate(p.verified_at)} · <span onClickCapture={() => onClick(r, "official_link_clicked")}><SourceLink href={p.official_url} /></span></p>
        </div>
      </div>
    </article>
  );
}

const hashListeners = new Set<() => void>();
function subscribeHash(cb: () => void): () => void {
  hashListeners.add(cb);
  window.addEventListener("hashchange", cb);
  return () => {
    hashListeners.delete(cb);
    window.removeEventListener("hashchange", cb);
  };
}

type Fetched = { key: string; result: { kind: "error"; message: string } | { kind: "ok"; data: RecommendResponse } };

export function Results() {
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => null);
  const req = useMemo<RecommendRequest | null | undefined>(() => (hash === null ? undefined : decodeRequest(hash)), [hash]);
  const [attempt, setAttempt] = useState(0);
  const [fetched, setFetched] = useState<Fetched | null>(null);
  const key = `${hash}|${attempt}`;

  useEffect(() => {
    if (!req) return;
    let cancelled = false;
    fetch(`${API}/api/v1/recommend`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(req), cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 429 ? "Too many requests — please wait a minute." : "We couldn't calculate recommendations.");
        return (await res.json()) as RecommendResponse;
      })
      .then((data) => !cancelled && setFetched({ key, result: { kind: "ok", data } }))
      .catch((e: unknown) => !cancelled && setFetched({ key, result: { kind: "error", message: e instanceof Error ? e.message : "Something went wrong." } }));
    return () => {
      cancelled = true;
    };
  }, [req, key]);

  const state: State = req === undefined ? { kind: "loading" } : req === null ? { kind: "missing" } :
    fetched && fetched.key === key ? fetched.result : { kind: "loading" };

  const update = (patch: Partial<CardRequest>) => {
    if (!req || req.product_type !== "credit_card") return;
    const next = { ...req, ...patch } as CardRequest;
    window.history.replaceState(null, "", `#${encodeRequest(next)}`);
    hashListeners.forEach((l) => l());
  };
  const retry = () => setAttempt((a) => a + 1);

  // one id per results view, for consented anonymous ranking events (sent only after an opt-in; DESIGN §26.7)
  const ok = state.kind === "ok" ? state.data : null;
  const listId = useMemo(() => (ok ? newListId() : ""), [ok]);
  useEffect(() => {
    if (!ok || !ok.results.length) return;
    void track({ event: "results_shown", list_id: listId, product_type: ok.product_type, shown: ok.results.map((r) => r.product.id), ranker: ok.ranker ?? "baseline" });
  }, [ok, listId]);
  const clicked: Clicked = (r, event) => {
    if (ok) void track({ event, list_id: listId, product_type: ok.product_type, product_id: r.product.id, position: r.rank, ranker: ok.ranker ?? "baseline" });
  };

  if (state.kind === "missing") return <EmptyState title="No answers yet" href="/recommend" cta="Start the questions">Answer a few questions to see recommendations.</EmptyState>;
  if (state.kind === "loading") return <SkeletonCards count={3} />;
  if (state.kind === "error") return <ErrorState retry={retry}>{state.message}</ErrorState>;
  const { data } = state;
  const card = req?.product_type === "credit_card" ? (req as CardRequest) : null;
  return (
    <div className="space-y-6">
      {card ? (
        <div className="grid gap-4 rounded-lg border border-border bg-surface-subtle p-4 md:grid-cols-2">
          <label className="flex flex-col text-sm font-medium text-ink-900">
            Value of a point or mile (cents)
            <span className="text-xs font-normal text-ink-500">Default assumes 1.0¢ per point unless the issuer publishes a fixed value.</span>
            <input type="number" step="0.1" min={0} max={5} defaultValue={card.cents_per_point ?? ""} placeholder="1.0"
              onBlur={(e) => update({ cents_per_point: e.target.value === "" ? null : e.target.value })}
              className="mt-1 min-h-11 w-32 rounded-md border border-border-strong bg-surface px-3 tabular" />
          </label>
          <CreditCheckboxes products={data.results.map((r) => r.product)} selected={card.selected_credit_ids ?? []}
            onChange={(ids) => update({ selected_credit_ids: ids })} />
        </div>
      ) : null}
      {data.results.length === 0 ? (
        <EmptyState title="No verified products match your answers" href="/recommend" cta="Change your answers">
          Only Verified products are recommended. {data.excluded?.length ? `${data.excluded.length} product(s) were excluded — see below.` : ""}
        </EmptyState>
      ) : (
        <ol className="space-y-6" aria-label="Ranked results">
          {data.results.map((r) => <li key={r.product.id}><ResultCard r={r} onClick={clicked} /></li>)}
        </ol>
      )}
      {data.excluded && data.excluded.length ? (
        <details className="rounded-md border border-border p-3 text-sm">
          <summary className="cursor-pointer font-medium text-ink-900">Excluded products ({data.excluded.length})</summary>
          <ul className="mt-2 list-disc pl-5">{data.excluded.map((e) => <li key={e.product_id}>{e.name}: {e.reason}</li>)}</ul>
        </details>
      ) : null}
      <EventConsent />
      <Disclaimer />
    </div>
  );
}
