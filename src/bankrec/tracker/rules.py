"""Checks one application or bonus rule (config/tracker/rules.yaml) against what a visitor said (DESIGN §27.10).

Every check is three-valued. A rule is a conflict only when the visitor's own answers meet its condition; it is clear
only when the answers rule the condition out (a complete card list, or a count they gave); anything else is
"unknown" with the question that would settle it. Nothing is assumed in the visitor's favour.

Severity: a met condition is a ``conflict`` when the rule is firm ("is not available") or names this very card;
a soft rule about other cards ("may not be available if you had any …") gives a ``possible_conflict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from bankrec.tracker.profile import HeldCard, MatchProfile

Tri = Literal["yes", "maybe", "no"]
Outcome = Literal["conflict", "possible_conflict", "unknown", "clear", "info"]

BANK_NAME = {
    "chase": "Chase",
    "american_express": "American Express",
    "citi": "Citi",
    "capital_one": "Capital One",
    "bank_of_america": "Bank of America",
    "discover": "Discover",
    "wells_fargo": "Wells Fargo",
    "other": "another bank",
}


@dataclass(frozen=True)
class CardFacts:
    """What the rules need to know about a tracked card."""

    card_key: str
    bank_id: str
    segment: str  # consumer | business
    name: str
    series: str | None = None
    reports_personal: bool | None = None
    annual_fee_cents: int | None = None


@dataclass
class Finding:
    rule: dict[str, Any]
    outcome: Outcome
    explanation: str
    needs: list[str] = field(default_factory=list)

    @property
    def effect(self) -> str:
        return str(self.rule["effect"])

    @property
    def basis(self) -> str:
        return str(self.rule["source_type"])


def months_ago(month: str, today: date) -> int:
    y, m = (int(x) for x in month.split("-"))
    return (today.year * 12 + today.month) - (y * 12 + m)


def within(month: str | None, window: int | None, today: date) -> Tri:
    """Opened (or received) within the last ``window`` months. Month precision: the boundary month is 'maybe'."""
    if window is None:
        return "yes"
    if month is None:
        return "maybe"
    ago = months_ago(month, today)
    return "yes" if ago < window else "maybe" if ago == window else "no"


def _and(*vals: Tri) -> Tri:
    return "no" if "no" in vals else "maybe" if "maybe" in vals else "yes"


def _card_name(a: HeldCard, facts: dict[str, CardFacts]) -> str:
    if a.card_key and a.card_key in facts:
        return facts[a.card_key].name
    kind = "business" if a.segment == "business" else "personal"
    return f"a {BANK_NAME.get(a.bank_id, a.bank_id)} {kind} card"


def account_matches(a: HeldCard, rule: dict[str, Any], card: CardFacts, facts: dict[str, CardFacts]) -> Tri:
    """Whether the visitor's account ``a`` is one the rule counts."""
    m = (rule.get("scope") or {}).get("match") or rule.get("match") or {}
    base: Tri
    target: set[str] | None = None
    if m.get("same_card"):
        target = {card.card_key}
    elif m.get("cards"):
        target = set(m["cards"])
    if target is not None:
        if a.card_key in target:
            base = "yes"
        elif (
            m.get("series_no_annual_fee_business")
            and a.bank_id == m["series_no_annual_fee_business"]
            and a.segment == "business"
        ):
            f = facts.get(a.card_key or "")
            fee_free: bool | None = (
                (f.annual_fee_cents == 0 if f.annual_fee_cents is not None else None)
                if f is not None
                else a.no_annual_fee
            )
            base = "yes" if fee_free is True else "no" if fee_free is False else "maybe"
        else:
            return "no"
    else:
        issuer = m.get("issuer", "any")
        if issuer != "any" and a.bank_id != issuer:
            return "no"
        base = "yes"
    seg = m.get("segment", "any")
    if seg == "business" and a.segment != "business":
        return "no"
    if seg == "personal" and a.segment == "business":
        if m.get("business_counts") != "per_card":
            return "no"
        f = facts.get(a.card_key or "")
        reports = f.reports_personal if f is not None else a.reports_to_personal
        if reports is False:
            return "no"
        if reports is None:
            base = _and(base, "maybe")
    if a.authorized_user:
        au = m.get("include_authorized_users")
        if au is False:
            return "no"
        if au is None:
            base = _and(base, "maybe")
    return base


@dataclass
class Count:
    lower: int
    upper: int | None  # None = cannot be bounded from the answers
    yes: list[HeldCard]
    maybe: list[HeldCard]


def count_opened(
    p: MatchProfile,
    rule: dict[str, Any],
    card: CardFacts,
    facts: dict[str, CardFacts],
    window: int,
    today: date,
) -> Count:
    yes, maybe = [], []
    for a in p.cards:
        if a.product_change:  # a product change opens no new account
            continue
        t = _and(account_matches(a, rule, card, facts), within(a.opened, window, today))
        if t == "yes":
            yes.append(a)
        elif t == "maybe":
            maybe.append(a)
    m = (rule.get("scope") or {}).get("match") or rule.get("match") or {}
    lower = len(yes)
    upper: int | None = len(yes) + len(maybe) if p.cards_complete else None
    q = p.new_accounts_24m
    if q is not None and window <= 24:
        if m.get("issuer", "any") == "any" and m.get("segment") == "personal":
            # the visitor's own count is exactly what an any-bank personal count rule needs (5/24)
            lower = max(lower, q)
            upper = max(q, lower)
        elif q == 0 and m.get("segment") == "personal":
            upper = len(yes) + len(maybe)
    return Count(lower, upper, yes, maybe)


def _fmt(cards: list[HeldCard], facts: dict[str, CardFacts]) -> str:
    names = [_card_name(a, facts) + (f" (opened {a.opened})" if a.opened else "") for a in cards[:6]]
    return "; ".join(names)


def _severity(rule: dict[str, Any]) -> Outcome:
    m = (rule.get("scope") or {}).get("match") or rule.get("match") or {}
    return "conflict" if rule.get("strength") == "firm" or m.get("same_card") else "possible_conflict"


def evaluate(
    rule: dict[str, Any], card: CardFacts, facts: dict[str, CardFacts], p: MatchProfile, today: date
) -> Finding:
    test = rule["test"]
    window: Any = rule.get("window_months")
    limit: Any = rule.get("limit") or rule.get("limit_count")
    hit = _severity(rule)
    bank = BANK_NAME.get(card.bank_id, card.bank_id)

    if test == "notice":
        return Finding(rule, "info", "How the issuer tells you about eligibility; nothing to check here.")

    if test == "count_limit":
        c = count_opened(p, rule, card, facts, int(window), today)
        if c.lower >= int(limit):
            src = (
                f"you said you opened {p.new_accounts_24m} card(s) in the last {window} months"
                if p.new_accounts_24m is not None and p.new_accounts_24m >= c.lower
                else f"your list has {c.lower} card(s) opened in the last {window} months: {_fmt(c.yes, facts)}"
            )
            return Finding(rule, hit, f"Met: {src}; the rule counts {limit} or more.")
        if c.upper is not None and c.upper < int(limit):
            return Finding(
                rule,
                "clear",
                f"Not met: {c.upper} card(s) opened in the last {window} months by your answers; the rule"
                f" counts {limit} or more.",
            )
        return Finding(
            rule,
            "unknown",
            f"Cannot tell: {c.lower} card(s) known in the last {window} months; the rule counts {limit} or more.",
            [f"How many credit cards you opened in the last {window} months, with any bank"],
        )

    if test in ("velocity", "interval"):
        pairs = rule.get("windows") or (rule.get("scope") or {}).get("windows") or [[window, 1]]
        unknown = False
        for w, lim in pairs:
            c = count_opened(p, rule, card, facts, int(w), today)
            if c.lower >= int(lim):
                return Finding(
                    rule,
                    hit,
                    f"Met: {c.lower} {bank} card(s) opened in the last {w} months ({_fmt(c.yes, facts)});"
                    f" the rule allows fewer than {lim}."
                    if test == "velocity"
                    else f"Met: you opened {_fmt(c.yes, facts)} within the last {w} months.",
                )
            if c.upper is None or c.upper >= int(lim):
                unknown = True
        if unknown:
            longest = max(int(w) for w, _ in pairs)
            return Finding(
                rule,
                "unknown",
                f"Cannot tell which {bank} cards you opened recently.",
                [f"Which {bank} cards you opened in the last {longest} months, and when"],
            )
        return Finding(rule, "clear", f"Not met: no {bank} cards opened in the window by your answers.")

    if test == "holding_count":
        yes = [a for a in p.cards if a.open_now is True and account_matches(a, rule, card, facts) == "yes"]
        maybe = [
            a
            for a in p.cards
            if a not in yes and a.open_now is not False and account_matches(a, rule, card, facts) != "no"
        ]
        if len(yes) >= int(limit):
            return Finding(
                rule, hit, f"Met: you hold {len(yes)} open {bank} personal cards ({_fmt(yes, facts)})."
            )
        if p.cards_complete and len(yes) + len(maybe) < int(limit):
            return Finding(
                rule, "clear", f"Not met: you hold {len(yes) + len(maybe)} open {bank} personal card(s)."
            )
        return Finding(rule, "unknown", f"Cannot tell how many open {bank} cards you have.",
                       [f"Which {bank} cards you have open now"])  # fmt: skip

    # card-history tests: holding, held_ever, bonus_lookback, holding_or_opened
    scope = rule.get("scope") or rule
    rel = [(a, account_matches(a, rule, card, facts)) for a in p.cards]
    rel = [(a, t) for a, t in rel if t != "no"]
    yes_hits: list[str] = []
    maybe_hits: list[str] = []

    def note(t: Tri, text: str) -> None:
        (yes_hits if t == "yes" else maybe_hits).append(text)

    for a, t in rel:
        name = _card_name(a, facts)
        held_now: Tri = "yes" if a.open_now is True else "no" if a.open_now is False else "maybe"
        if held_now != "no" and (
            test in ("holding", "holding_or_opened") or scope.get("also_current_holder")
        ):
            note(_and(t, held_now), f"you {'have' if held_now == 'yes' else 'may still have'} {name} open")
        if test == "held_ever":
            note(t, f"you have had {name}")
        if test == "held_ever" and scope.get("also_bonus_received") and a.bonus == "yes":
            note(t, f"you received the bonus on {name}")
        if test == "holding_or_opened" and not a.product_change:
            w = within(a.opened, window, today)
            if w != "no":
                note(_and(t, w), f"you opened {name}{f' in {a.opened}' if a.opened else ''}")
        if test == "bonus_lookback":
            if a.bonus == "yes":
                w = within(a.bonus_month, window, today)
                if w != "no":
                    when = f" in {a.bonus_month}" if a.bonus_month else " (month not given)"
                    note(_and(t, w), f"you received the bonus on {name}{when}")
            elif a.bonus == "unknown":
                note("maybe", f"you have had {name}, but not whether you received its bonus")
            if a.product_change and a.original_bonus_month:
                w = within(a.original_bonus_month, window, today)
                if w != "no":
                    note(_and(t, w), f"{name} came from a product change of a card whose bonus you received in"
                         f" {a.original_bonus_month}")  # fmt: skip
    span = f"in the last {window} months" if window else "ever"
    if yes_hits:
        return Finding(rule, hit, "Met: " + "; ".join(yes_hits) + ".")
    if maybe_hits:
        return Finding(rule, "unknown", "Possibly met: " + "; ".join(maybe_hits) + ".",
                       [f"The dates and bonus history of your {bank} cards"])  # fmt: skip
    if p.cards_complete:
        return Finding(rule, "clear", f"Not met: by your card list you have no matching {bank} card {span}.")
    return Finding(
        rule,
        "unknown",
        f"Cannot tell: you have not said whether you have or had {card.name}"
        + (" or a related card" if not ((scope.get("match") or {}).get("same_card")) else "")
        + (" or received its bonus" if test in ("bonus_lookback", "held_ever") else "")
        + ".",
        [f"Whether you have or had {card.name} (and when you received its bonus)"],
    )
