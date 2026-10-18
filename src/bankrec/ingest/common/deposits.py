"""Checking and savings extraction from the wording of real deposit pages (DESIGN §24.21).

Each reader returns the value and the page line(s) that state it (the provenance span), or None. They are written
against the official pages captured on 2026-10-18 (Chase, Capital One, Bank of America, U.S. Bank, American Express):

* monthly fee: "$15 or $0 Monthly Service Fee", "$12 Monthly Maintenance Fee", "Monthly maintenance fee" / "$8 or $0",
  "No monthly fees" / "There are no monthly fees" / "no monthly cycle service charge";
* fee waivers: the list after "You can avoid the fee by doing ONE of the following ...", "$0 for each statement cycle
  that:", "Extend waivers with any one of the following:"; every listed condition is kept, unrecognised ones as
  ``other`` (never dropped);
* minimum opening deposit: "minimum opening deposit of $25", "An initial deposit of at least $25 is required to open",
  "does not require a minimum balance to open", "no minimum balance to open", "No minimum balance is required to open";
* overdraft policy: the first sentence stating the overdraft fee policy;
* APY: a rate table ("Interest Rate" / "Annual Percentage Yield" / "0.01% 0.01%") or a headline ("Earn a 1.00% APY").
"""

from __future__ import annotations

import re
from decimal import Decimal

from bankrec.model import FeeWaiver
from bankrec.parsers.money import parse_money

_FEE_OR_ZERO = re.compile(
    r"\$(\d{1,3}(?:\.\d{2})?)\s+or\s+\$0\b(?:\s+(?:Monthly\s+(?:Service|Maintenance)\s+)?Fee)?", re.I
)
_FEE_AMOUNT = re.compile(r"\$(\d{1,3}(?:\.\d{2})?)\s+Monthly\s+(?:Service|Maintenance)\s+Fee\b", re.I)
_FEE_LABEL = re.compile(r"^monthly\s+(?:service|maintenance)\s+fee\b", re.I)
_NO_FEE = re.compile(
    r"\bno\s+monthly\s+(?:account\s+)?fees?\b|\bthere\s+are\s+no\s+monthly\s+fees\b|"
    r"\bno\s+monthly\s+(?:cycle\s+)?service\s+charge\b",
    re.I,
)


def monthly_fee(lines: list[str]) -> tuple[int, str] | None:
    """(fee cents, evidence). The fee charged when no waiver applies: "$15 or $0" → 1500."""
    for ln in lines:
        if m := _FEE_OR_ZERO.search(ln):
            return round(float(m.group(1)) * 100), ln
    for i, ln in enumerate(lines):
        if (
            _FEE_LABEL.match(ln.strip())
            and i + 1 < len(lines)
            and (m := _FEE_OR_ZERO.match(lines[i + 1].strip()))
        ):
            return round(float(m.group(1)) * 100), f"{ln} {lines[i + 1]}"
    for ln in lines:
        if (m := _FEE_AMOUNT.search(ln)) and float(m.group(1)) > 0:
            return round(float(m.group(1)) * 100), ln
    for ln in lines:
        if _NO_FEE.search(ln):
            return 0, ln
    return None


_WAIVER_START = re.compile(
    r"avoid\s+the\s+(?:monthly\s+service\s+)?fee\s+(?:by\s+doing|with)\s+one\s+of\s+the\s+following|"
    r"\$0\s+for\s+each\s+statement\s+cycle\s+that:|extend\s+waivers\s+with\s+any\s+one\s+of\s+the\s+following",
    re.I,
)
_WAIVER_SEP = re.compile(r"^-?\s*or\s*-?$", re.I)
_WAIVER_END = re.compile(
    r"^(?:see|read|to view|open|learn|how to|additional ways|what you need|review|apply|\$\d[\d.,]* or \$0$|"
    r"monthly maintenance fee|who can own|ways to pay|overdraft protection|how to avoid)\b",
    re.I,
)


def waiver_lines(lines: list[str], start_at: int = 0) -> list[str]:
    """The conditions listed after the first waiver introduction at or after ``start_at`` (separators dropped)."""
    for i in range(start_at, len(lines)):
        if not _WAIVER_START.search(lines[i]):
            continue
        out: list[str] = []
        for ln in lines[i + 1 : i + 20]:
            s = ln.strip()
            if not s or _WAIVER_SEP.match(s):
                continue
            if _WAIVER_END.match(s) or len(s) > 220:
                break
            if s.endswith(":") and not re.search(
                r"\d", s
            ):  # "Member of the following eligible customer groups:"
                continue
            out.append(s)
        return out
    return []


_AGE = re.compile(
    r"under\s+(?:the\s+)?age\s+(?:of\s+)?(?P<under>\d{2})|(?:age|ages)\s+(?P<lo>\d{2})\s*(?:-|–|to|through)\s*(?P<hi>\d{2})|"
    r"(?:age\s+)?(?P<min>\d{2})\s+(?:years\s+(?:or|and)\s+older|or\s+older|and\s+older|and\s+over)|"
    r"owners?\s+under\s+(?P<under2>\d{2})|(?P<lo2>\d{2})\s*-\s*(?P<hi2>\d{2})\s+year\s+olds",
    re.I,
)


def parse_waiver(st: str) -> FeeWaiver:
    """One listed condition. Unrecognised conditions are ``other`` with their text."""
    low = st.lower()
    amt = parse_money(st)
    kind = "other"
    age_min = age_max = None
    if re.search(r"(?:direct|electronic)\s+deposits?", low) and amt:
        kind = "direct_deposit_total" if "direct" in low else "electronic_deposit_total"
    elif re.search(r"average\s+(?:\w+\s+){0,3}balance", low) and amt:
        kind = "min_avg_balance"
    elif (
        re.search(
            r"(?:minimum\s+)?daily\s+balance|balance\s+at\s+the\s+beginning\s+of\s+each\s+day|balance\s+of",
            low,
        )
        and amt
    ):
        kind = "min_daily_balance"
    elif m := _AGE.search(st):
        kind = "age"
        if m.group("under") or m.group("under2"):
            age_max = int(m.group("under") or m.group("under2")) - 1
        elif m.group("lo") or m.group("lo2"):
            age_min, age_max = int(m.group("lo") or m.group("lo2")), int(m.group("hi") or m.group("hi2"))
        elif m.group("min"):
            age_min = int(m.group("min"))
    elif re.search(r"\blink(?:ed)?\b|\bown\s+or\s+open\b|\byou\s+own\b", low):
        kind = "linked_account"
    elif "student" in low:
        kind = "student"
    period = (
        "monthly"
        if re.search(r"\b(?:each|per|every)\s+(?:monthly\s+)?(?:statement|month)|monthly", low)
        else None
    )
    return FeeWaiver(
        kind=kind,
        amount_cents=amt
        if kind
        in {"direct_deposit_total", "electronic_deposit_total", "min_avg_balance", "min_daily_balance"}
        else None,
        age_min=age_min,
        age_max=age_max,
        period=period,
        text=st,
    )


_OPEN_ZERO = re.compile(
    r"(?:does\s+not\s+require|no)\s+(?:a\s+)?minimum\s+(?:balance|deposit)\s+(?:is\s+required\s+)?to\s+open|"
    r"no\s+minimum\s+balance\s+is\s+required\s+to\s+open|no\s+minimum\s+deposit\b|"
    r"no\s+minimum\s+balance\s+(?:required\s+)?to\s+open",
    re.I,
)
_OPEN_AMOUNT = re.compile(
    r"minimum\s+(?:opening\s+)?deposit\s+(?:of\s+|is\s+)?(?P<a>\$\d[\d,]*)|"
    r"initial\s+deposit\s+of\s+at\s+least\s+(?P<b>\$\d[\d,]*)\s+is\s+required\s+to\s+open|"
    r"(?P<c>\$\d[\d,]*)\s+minimum\s+(?:opening\s+)?deposit",
    re.I,
)


def opening_deposit(lines: list[str]) -> tuple[int, str] | None:
    for ln in lines:
        for sent in re.split(r"(?<=[a-z0-9)][.!?])\s+", ln):
            if m := _OPEN_AMOUNT.search(sent):
                amt = parse_money(m.group("a") or m.group("b") or m.group("c"))
                if amt is not None:
                    return amt, sent.strip()
    for ln in lines:
        for sent in re.split(r"(?<=[a-z0-9)][.!?])\s+", ln):
            if _OPEN_ZERO.search(sent):
                return 0, sent.strip()
    return None


_OVERDRAFT = re.compile(
    r"\b(?:no|\$0)\s+overdraft\s+(?:item\s+)?fees?\b|\boverdraft\s+fees?\s+—\s+\$\d+", re.I
)


def overdraft_summary(lines: list[str]) -> str | None:
    for ln in lines:
        for sent in re.split(r"(?<=[a-z0-9)][.!?])\s+", ln):
            if _OVERDRAFT.search(sent) and len(sent) < 300:
                return sent.strip()
    return None


_PCT_PAIR = re.compile(r"^(?P<rate>\d{1,2}\.\d{2})%\s+(?P<apy>\d{1,2}\.\d{2})%$")
_HEADLINE_APY = re.compile(r"(?P<apy>\d{1,2}\.\d{2})%\s*(?:APY|Annual\s+Percentage\s+Yield)", re.I)


def rate_table_apy(lines: list[str]) -> tuple[Decimal, str] | None:
    """The first "rate APY" pair after a table header naming Annual Percentage Yield ("0.01% 0.01%")."""
    for i, ln in enumerate(lines):
        if re.search(r"annual\s+percentage\s+yield|\bAPY\b", ln, re.I) and len(ln) < 60:
            for nxt in lines[i + 1 : i + 4]:
                if m := _PCT_PAIR.match(nxt.strip()):
                    return Decimal(m.group("apy")), nxt.strip()
    return None


def headline_apy(lines: list[str]) -> tuple[Decimal, str] | None:
    for ln in lines:
        if (m := _HEADLINE_APY.search(ln)) and not re.search(r"\bup\s+to\b|national", ln[: m.start()], re.I):
            return Decimal(m.group("apy")), ln.strip()
    return None
