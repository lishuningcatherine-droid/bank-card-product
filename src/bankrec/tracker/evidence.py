"""Review evidence for pending manual entries (owner 2026-11-11): every stored field next to the official page's own
words, with the source URL and a match / mismatch verdict. Read-only: pages are fetched under robots.txt and the rate
limit, nothing is stored in the database or published, and nothing is approved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bankrec.recommend.common import usd
from bankrec.tracker.manual import ManualCampaignIn

_WS = re.compile(r"\s+")


def norm(s: str | None) -> str:
    return _WS.sub(" ", s or "").strip()


@dataclass
class Row:
    field: str
    stored: str
    official: str
    verdict: str  # match | mismatch | not on page


def _find(text: str, needle: str) -> bool:
    return norm(needle).lower() in norm(text).lower()


def _context(text: str, needle: str, width: int = 140) -> str:
    t = norm(text)
    i = t.lower().find(norm(needle).lower())
    if i < 0:
        return ""
    a, b = max(0, i - 20), min(len(t), i + len(norm(needle)) + 20)
    out = t[a:b]
    return (("…" if a else "") + out + ("…" if b < len(t) else ""))[: width + 40]


_EXTRA_CARD = re.compile(r"additional card|authorized user|employee card", re.I)
_FEE = re.compile(r"\$([\d,]+)\s*annual fee|annual fee:?\s*\$([\d,]+)", re.I)


def _fee_hits(text: str) -> list[tuple[int, str]]:
    """The card's own annual fee mentions; fees for additional or authorized-user cards are left out."""
    t = norm(text)
    out = []
    for m in _FEE.finditer(t):
        before = re.split(r"[;.|]", t[max(0, m.start() - 60) : m.start()])[-1]
        after = re.split(r"[;.|]", t[m.end() : m.end() + 80])[0]
        if _EXTRA_CARD.search(before) or _EXTRA_CARD.search(after):  # the same clause is about another card
            continue
        out.append(
            (int((m.group(1) or m.group(2)).replace(",", "")) * 100, t[m.start() : m.end() + 40].strip())
        )
    return out


def _fees(text: str) -> list[int]:
    return sorted({c for c, _ in _fee_hits(text)})


def _fee_snippets(text: str) -> list[str]:
    return list(dict.fromkeys(s for _, s in _fee_hits(text)))[:3]


def _intro_fee(text: str) -> list[str]:
    t = norm(text)
    pat = r"[^.]{0,60}(?:intro(?:ductory)? annual fee|annual fee[^.]{0,40}first year|first year[^.]{0,40}annual fee)[^.]{0,60}"
    return [m.group(0).strip() for m in re.finditer(pat, t, re.I)][:2]


def _end_dates(text: str) -> list[str]:
    t = norm(text)
    pat = r"(?:offer ends|offer expires|expires on|apply by|must apply by|available through|ends on)\s+[A-Z][a-z]+\.? \d{1,2},? \d{4}(?:[^.]{0,30}(?:ET|EST|EDT|PT|CT))?"
    return [m.group(0) for m in re.finditer(pat, t, re.I)][:3]


def compare(entry: ManualCampaignIn, text: str) -> list[Row]:
    rows: list[Row] = []
    tier_ok = []
    for i, tier in enumerate(entry.tiers, 1):
        on_page = _find(text, tier.text)
        tier_ok.append(on_page)
        label = f"tier {i}" if len(entry.tiers) > 1 else "offer"
        rows.append(Row(f"{label}: offer sentence (verbatim)", tier.text, _context(text, tier.text) if on_page else "",
                        "match" if on_page else "not on page"))  # fmt: skip
        amount = f"{tier.amount:,}" if tier.unit in ("points", "miles") else usd(tier.amount)
        checks = [
            ("amount", f"{amount} {tier.unit_name or tier.unit}", amount),
            ("spend requirement", usd(tier.spend_cents) if tier.spend_cents is not None else "none", usd(tier.spend_cents) if tier.spend_cents is not None else None),
            ("window", f"{tier.window_count} {tier.window_unit}", f"{tier.window_count} {tier.window_unit}" if tier.window_count else None),
            ("window start", tier.window_start, {"account_opening": "account opening", "card_membership": "Card Membership",
                                                 "approval": "approv"}.get(tier.window_start)),
        ]  # fmt: skip
        for name, stored, token in checks:
            if token is None:
                rows.append(
                    Row(
                        f"{label}: {name}",
                        stored,
                        "(not stated)",
                        "match" if stored in ("none", "not_stated") else "mismatch",
                    )
                )
                continue
            ok = on_page and token.lower() in tier.text.lower()
            rows.append(
                Row(
                    f"{label}: {name}",
                    stored,
                    f"“…{token}…” in the offer sentence" if ok else "",
                    "match" if ok else "mismatch",
                )
            )
    # variable amount
    if entry.amount_qualifier == "up_to":
        phrase = next(
            (p for p in ("AS HIGH AS", "as high as", "up to", "Up to") if p.lower() in norm(text).lower()),
            None,
        )
        rows.append(Row("amount type", "variable (up to / as high as)", f"“{phrase}” on the page" if phrase else "",
                        "match" if phrase else "mismatch"))  # fmt: skip
        mins = re.findall(r"(?:at least|a minimum of|guaranteed)[^.]{0,60}points", norm(text), re.I)
        rows.append(Row("guaranteed minimum", str(entry.guaranteed_min) if entry.guaranteed_min is not None else "none",
                        "; ".join(mins[:2]) or "(no guaranteed minimum stated)",
                        "match" if (entry.guaranteed_min is None) == (not mins) else "mismatch"))  # fmt: skip
    else:
        rows.append(Row("amount type", entry.amount_qualifier, "fixed amount in the offer sentence",
                        "match" if all(tier_ok) else "not on page"))  # fmt: skip
    # restricted components
    for c in entry.offer_components:
        on = _find(text, c.text)
        rows.append(
            Row(
                "component: sentence (verbatim)",
                c.text,
                _context(text, c.text) if on else "",
                "match" if on else "not on page",
            )
        )
        for name, stored in (("component: amount", usd(c.amount_cents)), ("component: restriction", c.restriction),
                             ("component: expiry", c.expires or "none")):  # fmt: skip
            ok = on and (stored == "none" or stored.lower() in c.text.lower())
            rows.append(
                Row(
                    name,
                    stored,
                    f"“…{stored}…” in that sentence" if ok else "",
                    "match" if ok else "mismatch",
                )
            )
    # fees
    fees = _fees(text)
    snippets = _fee_snippets(text)
    if entry.annual_fee_cents is not None:
        ok = entry.annual_fee_cents in fees and len(fees) == 1
        rows.append(Row("annual fee", usd(entry.annual_fee_cents), " | ".join(snippets) or "(no annual fee stated)",
                        "match" if ok else "mismatch"))  # fmt: skip
    if entry.first_year_fee_cents is not None:
        intro = _intro_fee(text)
        ok = not intro and entry.first_year_fee_cents == entry.annual_fee_cents
        rows.append(Row("first-year fee", usd(entry.first_year_fee_cents),
                        " | ".join(intro) or "(no first-year waiver or intro fee stated: first year = annual fee)",
                        "match" if ok else "mismatch"))  # fmt: skip
    # deadline
    ends = _end_dates(text)
    stored_end = entry.end.text if entry.end else "unknown (none stated)"
    ok = (entry.end is None and not ends) or (entry.end is not None and _find(text, entry.end.text))
    rows.append(
        Row(
            "application deadline",
            stored_end,
            " | ".join(ends) or "(no end date stated)",
            "match" if ok else "mismatch",
        )
    )
    if entry.eligibility_text:
        on = _find(text, entry.eligibility_text)
        rows.append(Row("eligibility text (verbatim)", entry.eligibility_text, _context(text, entry.eligibility_text, 400) if on else "",
                        "match" if on else "not on page"))  # fmt: skip
    on = _find(text, entry.source_excerpt)
    rows.append(
        Row(
            "source excerpt (verbatim)",
            entry.source_excerpt,
            "found on the page" if on else "",
            "match" if on else "not on page",
        )
    )
    rows.append(
        Row(
            "channel",
            entry.channel,
            "public card page, no login or invitation",
            "match" if entry.channel == "public" else "mismatch",
        )
    )
    return rows


def _cell(s: str) -> str:
    return norm(s).replace("|", "\\|") or "—"


def markdown(
    entry_id: int, entry: ManualCampaignIn, rows: list[Row], url: str, how: str, at: datetime | None
) -> str:
    when = f"{at:%Y-%m-%d %H:%M} UTC" if at else "—"
    lines = [
        f"### Entry {entry_id}: `{entry.card_key}`",
        "",
        f"Source: {url} · read {when} · {how}",
        "",
        "| Stored field | Stored value | Official source text | Verdict |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {_cell(r.field)} | {_cell(r.stored)} | {_cell(r.official)} | **{r.verdict}** |" for r in rows
    ]
    bad = [r for r in rows if r.verdict != "match"]
    lines += ["", f"Result: {len(rows) - len(bad)} of {len(rows)} fields match." + (
        " Not matching: " + "; ".join(r.field for r in bad) + "." if bad else "")]  # fmt: skip
    return "\n".join(lines) + "\n"


def entry_of(payload: dict[str, Any]) -> ManualCampaignIn:
    return ManualCampaignIn.model_validate({k: v for k, v in payload.items() if k != "amendments"})
