"""Public views of campaigns, their history and the application rules (DESIGN §27.9). Read-only over prod."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.tracker import config, deadline, history, status, valuation

CHANNEL_LABEL = {
    "public": "Public application",
    "targeted": "Targeted invitation",
    "referral": "Referral link",
    "branch": "Branch application",
}
OFFER_TYPE_LABEL = {
    "welcome_bonus": "Welcome bonus",
    "spend_multiplier": "Limited-time earn boost",
    "first_year_fee": "First-year fee offer",
    "first_year_match": "First-year rewards match",
    "other": "Other offer",
}
SOURCE_LABEL = {
    "official": "Official page (read automatically)",
    "manual": "Official source (entered by hand, reviewed)",
    "third_party": "Third-party source (not confirmed by the issuer)",
}
CURRENT = ("active", "ending_soon", "pending_verification", "stale")


class Moment(BaseModel):
    date: str | None
    time: str | None
    time_known: bool
    stated_tz: str | None = None
    text: str | None = None
    confirmed: bool = False
    label: str


class Tier(BaseModel):
    amount: int | None
    unit: str
    unit_name: str | None = None
    spend_cents: int | None = None
    window_count: int | None = None
    window_unit: str | None = None
    window_start: str = "not_stated"
    incremental: bool = False
    text: str | None = None


class Component(BaseModel):
    """A restricted part of a welcome offer, shown on its own: never counted as cash, never converted to points."""

    kind: str
    amount_cents: int
    restriction: str
    expires: str | None = None
    text: str


class Terms(BaseModel):
    offer_type: str
    channel: str
    tiers: list[Tier]
    amount_qualifier: str | None = None
    total_amount: int | None
    guaranteed_min: int | None = None
    guaranteed_min_text: str | None = None
    offer_components: list[Component] = Field(default_factory=list)
    unit: str
    unit_name: str | None = None
    stated_cash_value_cents: int | None = None
    min_spend_cents: int | None
    window_count: int | None
    window_unit: str | None
    window_start: str
    annual_fee_cents: int | None
    first_year_fee_cents: int | None
    start: Moment | None
    end: Moment
    eligibility_text: str | None
    cap_text: str | None = None
    categories: list[str] = Field(default_factory=list)
    verbatim: str | None
    offer_url: str | None


class Value(BaseModel):
    cents: int | None
    depends_on_points_value: bool
    assumption: str | None
    cents_per_point: float | None
    first_year_net_cents: int | None
    first_year_fee_cents: int | None


class HistoryLabel(BaseModel):
    code: Literal[
        "insufficient_history",
        "variable_offer",
        "all_time_high",
        "above_usual",
        "recent_high",
        "usual",
        "below_usual",
    ]
    text: str
    records: int
    coverage_months: float
    median: float | None
    official_only: bool


class CardSummary(BaseModel):
    card_key: str
    product_id: str | None
    name: str
    bank_id: str
    bank_name: str
    segment: str
    series: str | None
    points_program: str | None
    points_program_name: str | None
    official_url: str | None
    annual_fee_cents: int | None
    first_year_fee_cents: int | None
    reports_to_personal_credit: dict[str, Any] | None
    counts_toward_chase_524: dict[str, Any] | None
    starter: Literal["student", "secured"] | None = None
    demo: bool


class VersionView(BaseModel):
    version: int
    valid_from: datetime
    valid_to: datetime | None
    terms: Terms
    change_summary: list[dict[str, Any]]
    source_url: str | None
    source_excerpt: str | None


class StatusEntry(BaseModel):
    at: datetime
    from_status: str | None
    to_status: str
    reason: str
    trigger: str
    actor: str | None


class CheckEntry(BaseModel):
    at: datetime
    outcome: str
    detail: str | None


class RuleView(BaseModel):
    rule_key: str
    bank_id: str
    name: str
    rule_type: str
    source_type: Literal["official", "community"]
    verification: str
    effect: Literal["approval", "bonus"]
    strength: str
    confidence: Literal["strong", "weak"] | None = None
    window_months: int | None
    source_url: str
    source_title: str | None
    excerpt: str
    notes: list[str]
    verified_at: date


class CampaignView(BaseModel):
    id: str
    campaign_key: str
    card: CardSummary
    channel: str
    channel_label: str
    offer_type: str
    offer_type_label: str
    status: str
    status_label: str
    status_reason: str | None
    source_kind: str
    source_label: str
    source_name: str | None
    officially_verified: bool
    first_seen_at: datetime
    last_checked_at: datetime | None
    last_verified_at: datetime | None
    version: int
    terms: Terms
    deadline_label: str
    countdown_to: datetime | None = Field(
        description="set only when the issuer stated both the date and the time (with its zone)"
    )
    value: Value
    history: HistoryLabel
    demo: bool


class CampaignDetail(CampaignView):
    versions: list[VersionView]
    status_log: list[StatusEntry]
    checks: list[CheckEntry]
    rules: list[RuleView]


class CampaignPage(BaseModel):
    items: list[CampaignView]
    total: int
    assumptions: list[str]


class PointValue(BaseModel):
    program: str
    name: str
    floor_cents: float | None
    basis: str | None = None
    source_url: str | None = None
    excerpt: str | None = None
    note: str | None = None


# ------------------------------------------------------------------------------------------------- builders


def moment(m: dict[str, Any] | None) -> Moment | None:
    if m is None:
        return None
    return Moment(
        date=m.get("date"),
        time=m.get("time"),
        time_known=bool(m.get("time_known")),
        stated_tz=m.get("stated_tz"),
        text=m.get("text"),
        confirmed=bool(m.get("confirmed")),
        label=deadline.label(m),
    )


def terms_view(t: dict[str, Any]) -> Terms:
    end = moment(t.get("end")) or moment(deadline.unknown())
    assert end is not None
    return Terms(
        **{
            k: t.get(k)
            for k in Terms.model_fields
            if k not in ("tiers", "start", "end", "categories", "window_start", "offer_components")
        },
        offer_components=[Component(**c) for c in t.get("offer_components") or []],
        tiers=[Tier(**{k: v for k, v in x.items() if k in Tier.model_fields}) for x in t.get("tiers") or []],
        window_start=t.get("window_start") or "not_stated",
        categories=list(t.get("categories") or []),
        start=moment(t.get("start")),
        end=end,
    )


def countdown(m: dict[str, Any] | None) -> datetime | None:
    """Only a confirmed deadline with a stated date, time and zone gets a countdown; never an estimate."""
    if not m or not m.get("confirmed") or not m.get("time_known") or not m.get("stated_tz"):
        return None
    return deadline.instant(m)


class Builder:
    def __init__(
        self, session: Session, *, allow_demo: bool, overrides: dict[str, float] | None = None
    ) -> None:
        self.s, self.allow_demo, self.overrides = session, allow_demo, overrides or {}
        self._banks = {b.bank_id: b.display_name for b in session.scalars(select(P.Bank))}
        self._cards = {c.card_key: c for c in session.scalars(select(P.TrackedCard))}
        self._products: dict[Any, P.Product] = {}

    def campaigns(self) -> list[P.Campaign]:
        q = select(P.Campaign)
        if not self.allow_demo:
            q = q.where(P.Campaign.demo.is_(False))
        return list(self.s.scalars(q))

    def product(self, card: P.TrackedCard) -> P.Product | None:
        if card.product_id is None:
            return None
        if card.product_id not in self._products:
            p = self.s.get(P.Product, card.product_id)
            if p is not None:
                self._products[card.product_id] = p
        return self._products.get(card.product_id)

    def card(self, key: str) -> CardSummary:
        c = self._cards[key]
        p = self.product(c)
        det = p.card if p is not None else None
        prog = config.programs().get(c.points_program or "") or {}
        return CardSummary(
            card_key=c.card_key,
            product_id=str(p.id) if p is not None else None,
            name=c.official_name,
            bank_id=c.bank_id,
            bank_name=self._banks.get(c.bank_id, c.bank_id),
            segment=c.segment,
            series=c.series,
            points_program=c.points_program,
            points_program_name=prog.get("name"),
            official_url=c.official_url,
            annual_fee_cents=det.annual_fee_cents if det else None,
            first_year_fee_cents=(
                det.intro_annual_fee_cents
                if det and det.intro_annual_fee_cents is not None
                else det.annual_fee_cents
            )
            if det
            else None,
            reports_to_personal_credit=c.reports_to_personal_credit,
            counts_toward_chase_524=c.counts_toward_chase_524,
            starter=c.starter,
            demo=c.demo,
        )

    def records(self, card_key: str, unit: str, current: P.Campaign) -> list[history.Record]:
        out = []
        for c in self.s.scalars(
            select(P.Campaign).where(
                P.Campaign.card_key == card_key,
                P.Campaign.channel == "public",
                P.Campaign.offer_type == current.offer_type,
            )
        ):
            latest = max(c.versions, key=lambda v: v.version)
            for v in c.versions:
                # a variable offer ("as high as") counts only at a published guaranteed minimum, else not at all
                amount = valuation.guaranteed_amount(v.terms)
                if amount is None or v.reward_unit != unit:
                    continue
                out.append(
                    history.Record(
                        amount=amount,
                        unit=unit,
                        valid_from=v.valid_from,
                        valid_to=v.valid_to,
                        official=c.source_kind in ("official", "manual"),
                        current=c.id == current.id and v.id == latest.id,
                    )
                )
        return out

    def view(self, c: P.Campaign, now: datetime) -> CampaignView:
        latest = max(c.versions, key=lambda v: v.version)
        t = latest.terms
        card = self._cards[c.card_key]
        st = c.status
        if st not in status.FINAL:
            # date-driven transitions are applied at read time too, so "ending soon"/"expired" never lag a sync
            st, _ = status.compute(
                c.status,
                end=t.get("end"),
                now=now,
                last_verified_at=c.last_verified_at if c.source_kind == "official" else None,
                consecutive_failures=c.consecutive_failures,
                not_seen=c.status == "pending_verification",
            )
        v = valuation.value(t, card.points_program, self.overrides)
        if valuation.guaranteed_amount(t) is None and valuation.is_variable(t):
            h = {
                "code": "variable_offer",
                "text": "Variable offer (stated as “as high as”, no published minimum): not compared with the"
                " history recorded on this site and never labelled as a high.",
                "records": 0,
                "coverage_months": 0,
                "median": None,
                "official_only": False,
            }
        else:
            h = history.label(self.records(c.card_key, t.get("unit") or "", c), now)
        return CampaignView(
            id=str(c.id),
            campaign_key=c.campaign_key,
            card=self.card(c.card_key),
            channel=c.channel,
            channel_label=CHANNEL_LABEL.get(c.channel, c.channel),
            offer_type=c.offer_type,
            offer_type_label=OFFER_TYPE_LABEL.get(c.offer_type, c.offer_type),
            status=st,
            status_label=status.LABEL[st],
            status_reason=c.status_reason if st == c.status else None,
            source_kind=c.source_kind,
            source_label=SOURCE_LABEL[c.source_kind],
            source_name=c.source_name,
            officially_verified=c.officially_verified,
            first_seen_at=c.first_seen_at,
            last_checked_at=c.last_checked_at,
            last_verified_at=c.last_verified_at,
            version=latest.version,
            terms=terms_view(t),
            deadline_label=deadline.label(t.get("end")),
            countdown_to=countdown(t.get("end")) if st in ("active", "ending_soon") else None,
            value=Value(
                cents=v["cents"],
                depends_on_points_value=v["depends_on_points_value"],
                assumption=v["assumption"],
                cents_per_point=v["cents_per_point"],
                first_year_net_cents=valuation.first_year_net(v, t),
                first_year_fee_cents=t.get("first_year_fee_cents"),
            ),
            history=HistoryLabel(**h),
            demo=c.demo,
        )

    def detail(self, c: P.Campaign, now: datetime) -> CampaignDetail:
        base = self.view(c, now)
        log = self.s.scalars(
            select(P.CampaignStatusLog)
            .where(P.CampaignStatusLog.campaign_id == c.id)
            .order_by(P.CampaignStatusLog.at)
        )
        checks = self.s.scalars(
            select(P.CampaignCheck)
            .where(P.CampaignCheck.campaign_id == c.id)
            .order_by(P.CampaignCheck.at.desc())
            .limit(30)
        )
        return CampaignDetail(
            **base.model_dump(),
            versions=[
                VersionView(
                    version=v.version,
                    valid_from=v.valid_from,
                    valid_to=v.valid_to,
                    terms=terms_view(v.terms),
                    change_summary=v.change_summary,
                    source_url=v.source_url,
                    source_excerpt=v.source_excerpt,
                )
                for v in sorted(c.versions, key=lambda v: v.version, reverse=True)
            ],
            status_log=[
                StatusEntry(
                    at=x.at,
                    from_status=x.from_status,
                    to_status=x.to_status,
                    reason=x.reason,
                    trigger=x.trigger,
                    actor=x.actor,
                )
                for x in log
            ],
            checks=[CheckEntry(at=x.at, outcome=x.outcome, detail=x.detail) for x in checks],
            rules=rules_for(self.s, self._cards[c.card_key]),
        )


def rule_view(r: P.ApplicationRule) -> RuleView:
    return RuleView(
        rule_key=r.rule_key,
        bank_id=r.bank_id,
        name=r.name,
        rule_type=r.rule_type,
        source_type=r.source_type,
        verification=r.verification,
        effect=r.effect,
        strength=r.strength,
        confidence=r.confidence,
        window_months=r.window_months,
        source_url=r.source_url,
        source_title=r.source_title,
        excerpt=r.excerpt,
        notes=list(r.notes or []),
        verified_at=r.verified_at,
    )


def applies(r: P.ApplicationRule, card: P.TrackedCard) -> bool:
    a = (r.scope or {}).get("applies_to") or {}
    if "cards" in a:
        return card.card_key in a["cards"]
    if a.get("bank_id") != card.bank_id:
        return False
    return not (a.get("segment") and a["segment"] != card.segment)


def rules_for(session: Session, card: P.TrackedCard) -> list[RuleView]:
    rows = session.scalars(select(P.ApplicationRule).where(P.ApplicationRule.bank_id == card.bank_id))
    return [rule_view(r) for r in rows if applies(r, card)]


def point_values() -> list[PointValue]:
    return [
        PointValue(
            program=k,
            name=v.get("name", k),
            floor_cents=v.get("floor_cents"),
            basis=v.get("basis"),
            source_url=v.get("source_url"),
            excerpt=v.get("excerpt"),
            note=v.get("note"),
        )
        for k, v in config.programs().items()
    ]


def assumptions() -> list[str]:
    return [
        "Cash back and statement credits count at face value.",
        "Points and miles count only at a cash or statement-credit value stated on an official page; without one,"
        " the offer shows the number of points and no dollar figure. You can enter your own value per program.",
        "First-year value = reward value minus the first-year annual fee. It does not include ongoing rewards.",
        "Deadlines are shown in US Eastern time (ET). A time is shown only when the issuer states one; a countdown"
        " only when the date, time and time zone are all stated.",
        "“Usual level” compares only with offers this site has recorded; with fewer than 3 records over 12 months"
        " no comparison is shown.",
    ]
