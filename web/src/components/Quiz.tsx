"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { CardRequest, CheckingRequest, SavingsRequest } from "@/lib/api/types";
import { encodeRequest } from "@/lib/request-hash";

import { Choice, NumberField, STATES, Toggle } from "./Field";

const IMPORTANCE = [["low", "Low"], ["medium", "Medium"], ["high", "High"]] as const;
const SPEND = [["groceries", "Groceries"], ["dining", "Dining"], ["travel", "Travel"], ["gas", "Gas"],
  ["entertainment", "Entertainment"], ["transit", "Transit"], ["online_shopping", "Online shopping"], ["other", "Everything else"]] as const;

function Submit() {
  return <button type="submit" className="min-h-11 rounded-md bg-navy-900 px-6 font-medium text-white hover:bg-navy-700">See my recommendations</button>;
}

function CardQuiz({ go }: { go: (r: CardRequest) => void }) {
  const [r, set] = useState<CardRequest>({
    product_type: "credit_card", goal: "cashback", monthly_spend: { groceries: 400, dining: 200, travel: 100, gas: 100, entertainment: 50, transit: 0, online_shopping: 100, other: 500 },
    travel_frequency: "occasional", preferred_reward: "any", max_annual_fee: 100, exclude_over_max_fee: true, avoid_foreign_fee: false,
    credit_profile: "unknown", segment: "consumer", include_co_branded: true, card_kind: "any", bonus_importance: "medium",
    selected_credit_ids: [], opt_in_rotating: false, opt_in_portal: false, opt_in_booked_direct: false,
  });
  const up = (p: Partial<CardRequest>) => set((x) => ({ ...x, ...p }));
  const spend = r.monthly_spend ?? { groceries: 0, dining: 0, travel: 0, gas: 0, entertainment: 0, transit: 0, online_shopping: 0, other: 0 };
  return (
    <form onSubmit={(e) => { e.preventDefault(); go(r); }} className="space-y-6">
      <Choice legend="Main goal" name="goal" value={r.goal} onChange={(goal) => up({ goal })}
        options={[["cashback", "Cash back"], ["travel", "Travel"], ["welcome_bonus", "Welcome bonus"], ["low_interest", "Low interest"], ["balance_transfer", "Balance transfer"], ["build_credit", "Build credit"]] as const} />
      <fieldset>
        <legend className="text-sm font-medium text-ink-900">Approximate monthly spending</legend>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {SPEND.map(([k, l]) => (
            <NumberField key={k} label={l} name={k} max={50000} value={(spend as Record<string, number>)[k] ?? 0}
              onChange={(v) => up({ monthly_spend: { ...spend, [k]: v } })} />
          ))}
        </div>
      </fieldset>
      <div className="grid gap-6 md:grid-cols-2">
        <Choice legend="How often do you travel?" name="travel" value={r.travel_frequency ?? "none"} onChange={(travel_frequency) => up({ travel_frequency })}
          options={[["none", "Rarely"], ["occasional", "A few times a year"], ["frequent", "Often"]] as const} />
        <Choice legend="Preferred reward type" name="reward" value={r.preferred_reward ?? "any"} onChange={(preferred_reward) => up({ preferred_reward })}
          options={[["any", "Any"], ["cashback", "Cash back"], ["points", "Points"], ["miles", "Miles"]] as const} />
        <div className="space-y-2">
          <NumberField label="Maximum annual fee" name="max_fee" max={1000} value={r.max_annual_fee ?? 0} onChange={(max_annual_fee) => up({ max_annual_fee })} />
          <Toggle label="Exclude cards above this fee entirely" checked={r.exclude_over_max_fee ?? true} onChange={(exclude_over_max_fee) => up({ exclude_over_max_fee })}
            hint="If off, a card over your limit is shown only when its estimated value exceeds the fee." />
        </div>
        <div className="space-y-2">
          <Toggle label="Avoid foreign transaction fees" checked={r.avoid_foreign_fee ?? false} onChange={(avoid_foreign_fee) => up({ avoid_foreign_fee })} />
          <Toggle label="Include co-branded cards (airline, hotel, retail)" checked={r.include_co_branded ?? true} onChange={(include_co_branded) => up({ include_co_branded })} />
          <Toggle label="Count rotating bonus categories" checked={r.opt_in_rotating ?? false} onChange={(opt_in_rotating) => up({ opt_in_rotating })}
            hint="Only up to each card's published quarterly cap, and only if you activate them." />
          <Toggle label="I book travel through the card issuer's travel portal" checked={r.opt_in_portal ?? false} onChange={(opt_in_portal) => up({ opt_in_portal })}
            hint="Counts portal-only rates (e.g. hotels booked through the issuer's travel site) on your travel spending." />
          <Toggle label="I book flights and hotels directly with the airline or hotel" checked={r.opt_in_booked_direct ?? false} onChange={(opt_in_booked_direct) => up({ opt_in_booked_direct })}
            hint="Counts rates that apply only to bookings made directly with the airline or hotel." />
        </div>
        <Choice legend="Credit profile (optional, broad)" name="credit" value={r.credit_profile ?? "unknown"} onChange={(credit_profile) => up({ credit_profile })}
          hint="Used only where the issuer publishes guidance." options={[["unknown", "Prefer not to say"], ["excellent", "Excellent"], ["good", "Good"], ["fair", "Fair"], ["limited", "Limited history"]] as const} />
        <Choice legend="Card for" name="segment" value={r.segment ?? "consumer"} onChange={(segment) => up({ segment })}
          options={[["consumer", "Personal use"], ["business", "Business"], ["either", "Either"]] as const} />
        <Choice legend="Student or secured card?" name="kind" value={r.card_kind ?? "any"} onChange={(card_kind) => up({ card_kind })}
          options={[["any", "No preference"], ["student", "Student card"], ["secured", "Secured card"]] as const} />
        <Choice legend="How important is a welcome bonus?" name="bonus" value={r.bonus_importance ?? "medium"} onChange={(bonus_importance) => up({ bonus_importance })} options={IMPORTANCE} />
      </div>
      <Submit />
    </form>
  );
}

function CheckingQuiz({ go }: { go: (r: CheckingRequest) => void }) {
  const [r, set] = useState<CheckingRequest>({ product_type: "checking", has_direct_deposit: true, monthly_direct_deposit: 2000,
    can_maintain_balance: false, approx_balance: 0, max_monthly_fee: 0, access_preference: "either", bonus_importance: "medium" });
  const up = (p: Partial<CheckingRequest>) => set((x) => ({ ...x, ...p }));
  return (
    <form onSubmit={(e) => { e.preventDefault(); go(r); }} className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-2">
          <Toggle label="I can set up direct deposit" checked={r.has_direct_deposit ?? false} onChange={(has_direct_deposit) => up({ has_direct_deposit })} />
          {r.has_direct_deposit ? <NumberField label="Approximate monthly direct deposit" name="dd" max={100000} value={r.monthly_direct_deposit ?? 0} onChange={(monthly_direct_deposit) => up({ monthly_direct_deposit })} /> : null}
        </div>
        <div className="space-y-2">
          <Toggle label="I can keep a minimum balance" checked={r.can_maintain_balance ?? false} onChange={(can_maintain_balance) => up({ can_maintain_balance })} />
          {r.can_maintain_balance ? <NumberField label="Roughly how much" name="bal" max={1000000} value={r.approx_balance ?? 0} onChange={(approx_balance) => up({ approx_balance })} /> : null}
        </div>
        <NumberField label="Maximum monthly fee you'd pay" name="fee" max={50} value={r.max_monthly_fee ?? 0} onChange={(max_monthly_fee) => up({ max_monthly_fee })} />
        <div className="space-y-2">
          <Toggle label="I can only deposit a limited amount to open the account" checked={r.max_opening_deposit != null}
            onChange={(on) => up({ max_opening_deposit: on ? 100 : null })}
            hint="Accounts are excluded only when the bank states a higher minimum opening deposit." />
          {r.max_opening_deposit != null ? <NumberField label="Most I can deposit to open" name="open" max={1000000} value={r.max_opening_deposit} onChange={(max_opening_deposit) => up({ max_opening_deposit })} /> : null}
        </div>
        <label className="flex flex-col text-sm font-medium text-ink-900">
          State
          <select value={r.state ?? ""} onChange={(e) => up({ state: (e.target.value || null) as CheckingRequest["state"] })} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal">
            <option value="">Prefer not to say</option>
            {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <Choice legend="Branch or online?" name="access" value={r.access_preference ?? "either"} onChange={(access_preference) => up({ access_preference })}
          options={[["either", "Either"], ["branch", "Branch"], ["online", "Online"]] as const} />
        <Choice legend="How important is a bonus?" name="bonus" value={r.bonus_importance ?? "medium"} onChange={(bonus_importance) => up({ bonus_importance })} options={IMPORTANCE} />
      </div>
      <Submit />
    </form>
  );
}

function SavingsQuiz({ go }: { go: (r: SavingsRequest) => void }) {
  const [r, set] = useState<SavingsRequest>({ product_type: "savings", deposit_range: "5k_25k", holding_months: 12, liquidity_need: "medium", max_monthly_fee: 0, apy_vs_bonus: "balanced" });
  const up = (p: Partial<SavingsRequest>) => set((x) => ({ ...x, ...p }));
  return (
    <form onSubmit={(e) => { e.preventDefault(); go(r); }} className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        <Choice legend="How much would you deposit?" name="dep" value={r.deposit_range} onChange={(deposit_range) => up({ deposit_range })}
          options={[["lt_1k", "Under $1,000"], ["1k_5k", "$1,000–$5,000"], ["5k_25k", "$5,000–$25,000"], ["25k_100k", "$25,000–$100,000"], ["100k_plus", "$100,000+"]] as const} />
        <NumberField label="How long would you keep it there (months)?" name="months" prefix="" min={1} max={60} value={r.holding_months ?? 12} onChange={(holding_months) => up({ holding_months })} />
        <Choice legend="How often might you need to withdraw?" name="liq" value={r.liquidity_need ?? "medium"} onChange={(liquidity_need) => up({ liquidity_need })}
          options={[["low", "Rarely"], ["medium", "Sometimes"], ["high", "Often"]] as const} />
        <NumberField label="Maximum monthly fee you'd pay" name="fee" max={50} value={r.max_monthly_fee ?? 0} onChange={(max_monthly_fee) => up({ max_monthly_fee })} />
        <label className="flex flex-col text-sm font-medium text-ink-900">
          State
          <select value={r.state ?? ""} onChange={(e) => up({ state: (e.target.value || null) as SavingsRequest["state"] })} className="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-normal">
            <option value="">Prefer not to say</option>
            {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <Choice legend="What matters more?" name="prio" value={r.apy_vs_bonus ?? "balanced"} onChange={(apy_vs_bonus) => up({ apy_vs_bonus })}
          options={[["apy", "Ongoing APY"], ["balanced", "Balanced"], ["bonus", "Bonus"]] as const} />
      </div>
      <Submit />
    </form>
  );
}

export function Quiz({ type }: { type: "credit-card" | "checking" | "savings" }) {
  const router = useRouter();
  const go = (r: CardRequest | CheckingRequest | SavingsRequest) => router.push(`/recommend/results#${encodeRequest(r)}`);
  if (type === "credit-card") return <CardQuiz go={go} />;
  if (type === "checking") return <CheckingQuiz go={go} />;
  return <SavingsQuiz go={go} />;
}
