"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Assessment, HeldCard, Judgement, MatchFinding, MatchProfile, MatchResponse } from "@/lib/api/types";
import { longDate, usd } from "@/lib/format";
import { decodeRequest } from "@/lib/request-hash";

import { SourceLink } from "./SourceLink";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const KEY = "offer-check-profile";

/** Answers stay in this browser: sessionStorage by default, localStorage only when the visitor asks to remember them.
 * They are sent only to compute the result; the server never stores or logs them. */
function loadSaved(): { p: MatchProfile; remember: boolean } | null {
  try {
    const local = window.localStorage.getItem(KEY);
    if (local) return { p: JSON.parse(local) as MatchProfile, remember: true };
    const ses = window.sessionStorage.getItem(KEY);
    if (ses) return { p: JSON.parse(ses) as MatchProfile, remember: false };
  } catch {
    /* storage unavailable */
  }
  return null;
}

function save(p: MatchProfile, remember: boolean): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(p));
    if (remember) window.localStorage.setItem(KEY, JSON.stringify(p));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}

function clean(p: MatchProfile): MatchProfile {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(p)) if (v !== null && v !== undefined && v !== "") out[k] = v;
  return out as MatchProfile;
}

const BANKS = [
  ["chase", "Chase"], ["american_express", "American Express"], ["citi", "Citi"], ["capital_one", "Capital One"],
  ["bank_of_america", "Bank of America"], ["discover", "Discover"], ["wells_fargo", "Wells Fargo"], ["other", "Another bank"],
] as const;

export type CardOption = { card_key: string; bank_id: string; name: string; segment: string };

// ------------------------------------------------------------------------------------------- badges

const ACTION_STYLE: Record<string, string> = {
  consider_now: "bg-positive-bg text-positive",
  verify_first: "bg-info-bg text-info",
  improve_credit: "bg-warning-bg text-warning",
  not_suitable: "bg-expired-bg text-expired",
};

/** The four kinds of judgement are always marked differently (brief §4). */
export function KindBadge({ kind }: { kind: "official" | "community" | "profile" | "unconfirmed" }) {
  const map = {
    official: ["bg-navy-50 text-navy-900", "Official bank rule"],
    community: ["bg-unverified-bg text-unverified", "Community-reported rule"],
    profile: ["bg-positive-bg text-positive", "Based on your answers"],
    unconfirmed: ["bg-recheck-bg text-recheck", "Not confirmed / not enough information"],
  } as const;
  const [cls, text] = map[kind];
  return <span className={`inline-flex rounded-sm px-2 py-0.5 text-xs font-medium ${cls}`}>{text}</span>;
}

function findingKind(f: MatchFinding): "official" | "community" | "unconfirmed" {
  if (f.outcome === "unknown") return "unconfirmed";
  return f.basis === "official" ? "official" : "community";
}

function Finding({ f }: { f: MatchFinding }) {
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-ink-900">{f.outcome_label}</span>
        <KindBadge kind={findingKind(f)} />
        {f.outcome === "unknown" ? <KindBadge kind={f.basis === "official" ? "official" : "community"} /> : null}
        {f.verification === "third_party_quote" ? <span className="text-xs text-ink-500">bank wording quoted by a third party</span> : null}
        <span className="text-xs text-ink-500">affects {f.effect === "approval" ? "approval" : "the bonus"}</span>
      </div>
      <p className="mt-1 text-ink-900">{f.name}</p>
      <p className="mt-1 text-ink-700">{f.explanation}</p>
      <details className="mt-1 text-xs text-ink-500">
        <summary className="cursor-pointer">Source wording</summary>
        <blockquote className="mt-1 border-l-2 border-border pl-3">“{f.excerpt}”</blockquote>
        <p className="mt-1"><SourceLink href={f.source_url}>{f.source_title ?? "Source"}</SourceLink> · checked {longDate(f.verified_at)}</p>
      </details>
    </li>
  );
}

function JudgementBlock({ title, j, kind }: { title: string; j: Judgement; kind?: "profile" | "unconfirmed" }) {
  const k = kind ?? (j.status === "unknown" || j.status === "needs_info" || j.status === "no_comparison" ? "unconfirmed" : "profile");
  return (
    <section className="rounded-md border border-border p-3 text-sm" aria-label={title}>
      <h4 className="text-sm font-medium text-ink-500">{title}</h4>
      <p className="mt-1 flex flex-wrap items-center gap-2 font-medium text-ink-900">{j.label} <KindBadge kind={k} /></p>
      {j.points?.length ? <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-700">{j.points.map((x) => <li key={x}>{x}</li>)}</ul> : null}
    </section>
  );
}

export function AssessmentCard({ a }: { a: Assessment }) {
  const shown = a.eligibility.filter((f) => f.outcome !== "clear" && f.outcome !== "info");
  const clear = a.eligibility.filter((f) => f.outcome === "clear");
  return (
    <article className="rounded-lg border border-border bg-surface p-5 shadow-card" aria-labelledby={`a-${a.campaign_id}`}>
      <p className="text-sm text-ink-500">{a.bank_name}</p>
      <h3 id={`a-${a.campaign_id}`} className="text-lg"><Link href={`/offers/${a.campaign_id}`}>{a.card_name}</Link></h3>
      <div className={`mt-2 rounded-md p-3 ${ACTION_STYLE[a.action]}`}>
        <p className="font-semibold">Suggested action: {a.action_label}</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{a.action_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      </div>
      {a.conflicts.length ? (
        <section className="mt-3" aria-label="Known conflicts">
          <h4 className="text-base text-expired">Known eligibility conflicts (shown first; a large reward does not offset them)</h4>
          <ul className="mt-2 space-y-2">{a.conflicts.map((f) => <Finding key={f.rule_key} f={f} />)}</ul>
        </section>
      ) : null}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <JudgementBlock title="Can you be approved?" j={a.approval} />
        <JudgementBlock title="Can you earn this bonus?" j={a.bonus} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <JudgementBlock title="1. Offer appeal" j={a.offer_appeal} />
        <JudgementBlock title="2. Personal fit" j={a.personal_fit} />
        <JudgementBlock title="3. Reaching the spend" j={{ status: a.reach.status, label: a.reach.label, points: [a.reach.text, ...(a.reach.tiers ?? []).map((t) => `Tier: ${t.reward} after ${t.spend_cents != null ? usd(t.spend_cents) : "an unstated amount"} — ${t.status}`)] }} />
      </div>
      {shown.filter((f) => f.outcome !== "conflict").length ? (
        <section className="mt-3" aria-label="Other rules">
          <h4 className="text-base">4. Other application and bonus rules</h4>
          <ul className="mt-2 space-y-2">{shown.filter((f) => f.outcome !== "conflict").map((f) => <Finding key={f.rule_key} f={f} />)}</ul>
        </section>
      ) : null}
      {clear.length ? <p className="mt-2 text-xs text-ink-500">No conflict found by your answers: {clear.map((f) => f.name).join("; ")}.</p> : null}
      <section className="mt-3 rounded-md bg-surface-subtle p-3 text-sm" aria-label="Uncertainty">
        <h4 className="flex flex-wrap items-center gap-2 text-base">5. What is uncertain <KindBadge kind="unconfirmed" /></h4>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-700">{a.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul>
      </section>
      <p className="mt-3 text-sm"><span className="font-medium text-ink-900">First-year value:</span> {a.first_year.text}
        {a.first_year.depends_on_points_value ? <span className="text-ink-500"> (depends on the value of points)</span> : null}</p>
    </article>
  );
}

// ------------------------------------------------------------------------------------------- form

function Sel<T extends string>({ label, value, options, onChange, hint }: {
  label: string; value: T | null | undefined; options: readonly (readonly [T, string])[]; onChange: (v: T | null) => void; hint?: string;
}) {
  return (
    <label className="flex flex-col text-sm font-medium text-ink-900">
      {label}
      {hint ? <span className="text-xs font-normal text-ink-500">{hint}</span> : null}
      <select value={value ?? ""} onChange={(e) => onChange((e.target.value || null) as T | null)}
        className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal">
        <option value="">Not answered</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function Num({ label, value, onChange, hint, max, prefix }: {
  label: string; value: number | null | undefined; onChange: (v: number | null) => void; hint?: string; max: number; prefix?: string;
}) {
  return (
    <label className="flex flex-col text-sm font-medium text-ink-900">
      {label}
      {hint ? <span className="text-xs font-normal text-ink-500">{hint}</span> : null}
      <span className="mt-1 flex items-center rounded-md border border-border-strong bg-surface">
        {prefix ? <span className="pl-3 text-ink-500" aria-hidden="true">{prefix}</span> : null}
        <input type="number" inputMode="numeric" min={0} max={max} value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Math.max(0, Math.min(max, Math.round(Number(e.target.value) || 0))))}
          className="min-h-11 w-full rounded-md bg-transparent px-3 font-normal outline-none" />
      </span>
    </label>
  );
}

const YESNO = [["yes", "Yes"], ["no", "No"]] as const;
const yn = (b: boolean | null | undefined) => (b == null ? null : b ? "yes" : "no");
const toBool = (v: string | null) => (v == null ? null : v === "yes");

function CardRow({ c, cards, onChange, onRemove }: { c: HeldCard; cards: CardOption[]; onChange: (c: HeldCard) => void; onRemove: () => void }) {
  return (
    <li className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-2 lg:grid-cols-3">
      <label className="flex flex-col text-sm font-medium text-ink-900">Card
        <select value={c.card_key ?? `other:${c.bank_id}:${c.segment}`} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal"
          onChange={(e) => {
            const v = e.target.value;
            if (v.startsWith("other:")) {
              const [, bank, seg] = v.split(":");
              onChange({ ...c, card_key: null, bank_id: bank as HeldCard["bank_id"], segment: seg as HeldCard["segment"] });
            } else {
              const o = cards.find((x) => x.card_key === v);
              onChange({ ...c, card_key: v, bank_id: (o?.bank_id ?? "other") as HeldCard["bank_id"], segment: o?.segment === "business" ? "business" : "personal" });
            }
          }}>
          {cards.map((o) => <option key={o.card_key} value={o.card_key}>{o.name}</option>)}
          {BANKS.flatMap(([b, n]) => [["personal", "personal"], ["business", "business"]].map(([s, l]) => <option key={`${b}${s}`} value={`other:${b}:${s}`}>{`Other ${n} ${l} card`}</option>))}
        </select>
      </label>
      <label className="flex flex-col text-sm font-medium text-ink-900">Opened (month)
        <input type="month" value={c.opened ?? ""} onChange={(e) => onChange({ ...c, opened: e.target.value || null })} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal" />
      </label>
      <Sel label="Still open?" value={yn(c.open_now)} options={YESNO} onChange={(v) => onChange({ ...c, open_now: toBool(v) })} />
      <Sel label="Received its welcome bonus?" value={c.bonus ?? "unknown"} options={[["yes", "Yes"], ["no", "No"], ["unknown", "Not sure"]] as const} onChange={(v) => onChange({ ...c, bonus: v ?? "unknown" })} />
      {c.bonus === "yes" ? (
        <label className="flex flex-col text-sm font-medium text-ink-900">Bonus received (month)
          <input type="month" value={c.bonus_month ?? ""} onChange={(e) => onChange({ ...c, bonus_month: e.target.value || null })} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal" />
        </label>
      ) : null}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!c.authorized_user} onChange={(e) => onChange({ ...c, authorized_user: e.target.checked })} className="size-5 accent-navy-900" /> Authorized-user card</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!c.product_change} onChange={(e) => onChange({ ...c, product_change: e.target.checked })} className="size-5 accent-navy-900" /> Became this card through a product change</label>
      {c.product_change ? (
        <label className="flex flex-col text-sm font-medium text-ink-900">Bonus on the original card (month, if any)
          <input type="month" value={c.original_bonus_month ?? ""} onChange={(e) => onChange({ ...c, original_bonus_month: e.target.value || null })} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal" />
        </label>
      ) : null}
      <button type="button" onClick={onRemove} className="min-h-11 justify-self-start rounded-md border border-border-strong px-4 text-sm">Remove</button>
    </li>
  );
}

type State = { kind: "idle" } | { kind: "loading" } | { kind: "error"; message: string } | { kind: "ok"; data: MatchResponse };

export function MatchCheck({ campaignId, cards, pointValues }: { campaignId?: string; cards: CardOption[]; pointValues: Record<string, number> }) {
  const [p, setP] = useState<MatchProfile>({});
  const [remember, setRemember] = useState(false);
  const [onlyOne, setOnlyOne] = useState(!!campaignId);
  const [state, setState] = useState<State>({ kind: "idle" });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const saved = loadSaved();
    let next: MatchProfile = saved?.p ?? {};
    // answers carried over from the card questionnaire (URL fragment only)
    const req = decodeRequest(window.location.hash);
    if (req && req.product_type === "credit_card") {
      const total = Object.values(req.monthly_spend ?? {}).reduce((s, v) => s + (v ?? 0), 0);
      next = {
        ...next,
        spend_categories: req.monthly_spend,
        monthly_spend: next.monthly_spend ?? (total || null),
        max_annual_fee: next.max_annual_fee ?? req.max_annual_fee ?? null,
        reward_preference: next.reward_preference ?? (req.preferred_reward === "cashback" ? "cashback" : req.preferred_reward === "any" ? "any" : "points"),
      };
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reading browser-only storage once on mount
    setP(next);
    setRemember(saved?.remember ?? false);
    setLoaded(true);
  }, []);

  const up = (patch: Partial<MatchProfile>) => setP((old) => ({ ...old, ...patch }));
  const held = p.cards ?? [];

  async function run() {
    const profile = clean(p);
    save(profile, remember);
    setState({ kind: "loading" });
    try {
      const res = await fetch(`${API}/api/v1/campaigns/match`, {
        method: "POST", headers: { "content-type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ profile, campaign_ids: onlyOne && campaignId ? [campaignId] : null, point_values: pointValues }),
      });
      if (!res.ok) throw new Error(res.status === 422 ? "Some answers are not valid; please check them." : `The service answered ${res.status}.`);
      setState({ kind: "ok", data: (await res.json()) as MatchResponse });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : "Something went wrong." });
    }
  }

  function forget() {
    try {
      window.localStorage.removeItem(KEY);
      window.sessionStorage.removeItem(KEY);
    } catch {
      /* storage unavailable */
    }
    setP({});
    setState({ kind: "idle" });
  }

  if (!loaded) return <p className="text-sm text-ink-500">Loading…</p>;
  return (
    <div className="space-y-6">
      <form className="space-y-5 rounded-lg border border-border bg-surface p-5" onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <section aria-labelledby="q-basic" className="space-y-3">
          <h2 id="q-basic" className="text-lg">Start with four questions</h2>
          <p className="text-sm text-ink-500">Leave anything you don&apos;t know empty: the result then says what to confirm instead of assuming you qualify. We never ask for your SSN, EIN, card numbers or bank logins.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Sel label="How long have you had credit?" value={p.credit_history} onChange={(v) => up({ credit_history: v })}
              options={[["none", "No credit history"], ["lt_1y", "Less than 1 year"], ["1_2y", "1–2 years"], ["2_5y", "2–5 years"], ["5y_plus", "More than 5 years"]] as const} />
            <Num label="Normal monthly card spending" prefix="$" max={100000} value={p.monthly_spend} onChange={(v) => up({ monthly_spend: v })}
              hint="What you already spend — never extra spending to reach a bonus" />
            <Num label="Credit cards opened in the last 24 months (any bank)" max={60} value={p.new_accounts_24m} onChange={(v) => up({ new_accounts_24m: v })}
              hint="Include authorized-user cards and business cards that appear on your personal credit report" />
            <Sel label="Late payments, collections or bankruptcy on your report?" value={yn(p.negative_marks)} options={YESNO} onChange={(v) => up({ negative_marks: toBool(v) })} />
          </div>
        </section>

        <details className="rounded-md border border-border p-4" open={held.length > 0 || p.credit_score != null}>
          <summary className="cursor-pointer font-medium text-ink-900">More details (improves the check)</summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Num label="Credit score (optional)" max={850} value={p.credit_score} onChange={(v) => up({ credit_score: v == null ? null : Math.max(300, v) })} hint="One signal only; never decisive" />
            <Sel label="Score model" value={p.score_model} onChange={(v) => up({ score_model: v })}
              options={[["fico", "FICO"], ["vantage", "VantageScore"], ["other", "Other"], ["unknown", "Don't know"]] as const} />
            <Num label="Most you would pay in annual fees" prefix="$" max={1000} value={p.max_annual_fee} onChange={(v) => up({ max_annual_fee: v })} />
            <Sel label="Rewards you prefer" value={p.reward_preference} onChange={(v) => up({ reward_preference: v })}
              options={[["cashback", "Cash back"], ["points", "Travel points or miles"], ["any", "Either"]] as const} />
            <Sel label="Business or side income?" value={p.business_income} onChange={(v) => up({ business_income: v })}
              options={[["yes", "Yes"], ["no", "No"], ["unsure", "Not sure"]] as const}
              hint="For business cards. A sole proprietor can usually apply with their own SSN; we don't collect it." />
            <Sel label="Student?" value={yn(p.student)} options={YESNO} onChange={(v) => up({ student: toBool(v) })} />
          </div>
          <fieldset className="mt-4">
            <legend className="text-sm font-medium text-ink-900">Banks where you have a checking or savings account</legend>
            <div className="mt-1 flex flex-wrap gap-3">
              {BANKS.filter(([b]) => b !== "other").map(([b, n]) => (
                <label key={b} className="flex min-h-11 items-center gap-2 text-sm">
                  <input type="checkbox" className="size-5 accent-navy-900" checked={(p.bank_relationships ?? []).includes(b)}
                    onChange={(e) => up({ bank_relationships: e.target.checked ? [...(p.bank_relationships ?? []), b] : (p.bank_relationships ?? []).filter((x) => x !== b) })} />
                  {n}
                </label>
              ))}
            </div>
          </fieldset>
          <section className="mt-4" aria-labelledby="q-cards">
            <h3 id="q-cards" className="text-base">Cards you have or had</h3>
            <p className="text-sm text-ink-500">Needed for “once per lifetime”, 48-month and similar bonus rules, and for Chase 5/24 and Bank of America 2/3/4.</p>
            <ul className="mt-2 space-y-2">
              {held.map((c, i) => (
                <CardRow key={i} c={c} cards={cards}
                  onChange={(n) => up({ cards: held.map((x, j) => (j === i ? n : x)) })}
                  onRemove={() => up({ cards: held.filter((_, j) => j !== i) })} />
              ))}
            </ul>
            <button type="button" className="mt-2 min-h-11 rounded-md border border-border-strong px-4 text-sm"
              onClick={() => up({ cards: [...held, { card_key: cards[0]?.card_key ?? null, bank_id: (cards[0]?.bank_id ?? "other") as HeldCard["bank_id"], segment: "personal", bonus: "unknown" }] })}>
              Add a card
            </button>
            <label className="mt-3 flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 size-5 accent-navy-900" checked={!!p.cards_complete} onChange={(e) => up({ cards_complete: e.target.checked })} />
              This list includes every credit card I have had, open or closed, including authorized-user cards (tick this if you have never had a card and the list is empty).
            </label>
          </section>
        </details>

        <div className="flex flex-wrap items-center gap-4">
          {campaignId ? (
            <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-5 accent-navy-900" checked={onlyOne} onChange={(e) => setOnlyOne(e.target.checked)} /> Only the offer I came from</label>
          ) : null}
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-5 accent-navy-900" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember my answers on this device</label>
        </div>
        <div className="flex flex-wrap gap-3">
          <button type="submit" className="inline-flex min-h-11 items-center rounded-md bg-navy-900 px-5 font-medium text-white hover:bg-navy-700">Check offers for me</button>
          <button type="button" onClick={forget} className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-5">Clear my answers</button>
        </div>
        <p className="text-xs text-ink-500">Your answers stay in this browser ({remember ? "saved on this device until you clear them" : "for this tab only"}). They are sent only to compute the result; the server does not store or log them.</p>
      </form>

      {state.kind === "loading" ? <p role="status" className="text-sm text-ink-500">Checking…</p> : null}
      {state.kind === "error" ? <p role="alert" className="rounded-md bg-expired-bg p-3 text-sm text-expired">{state.message}</p> : null}
      {state.kind === "ok" ? (
        <section aria-labelledby="results" className="space-y-4">
          <h2 id="results" className="text-xl">Results ({state.data.items.length})</h2>
          {state.data.questions.length ? (
            <div className="rounded-md bg-info-bg p-3 text-sm text-info">
              <p className="font-medium">Answer these next for a firmer result:</p>
              <ul className="mt-1 list-disc pl-5">{state.data.questions.map((q) => <li key={q.key}>{q.text} <span className="opacity-80">— {q.why}</span></li>)}</ul>
            </div>
          ) : null}
          {state.data.items.map((a) => <AssessmentCard key={a.campaign_id} a={a} />)}
          <details className="text-sm"><summary className="cursor-pointer">How this check works</summary>
            <ul className="mt-1 list-disc pl-5 text-ink-700">{state.data.assumptions.map((x) => <li key={x}>{x}</li>)}</ul>
          </details>
          <p className="text-xs text-ink-500">{state.data.disclaimer}</p>
        </section>
      ) : null}
    </div>
  );
}
