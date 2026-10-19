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


_TIER_HEADER = re.compile(r"^(?:account\s+)?balance\s+(?:interest\s+)?rate\s+APY$", re.I)
_TIER_ROW = re.compile(r"^(?P<lab>.+?)\s+(?P<rate>\d{1,2}\.\d{2})%\s+(?P<apy>\d{1,2}\.\d{2})%$")


def _tier_bounds(label: str) -> tuple[int, int | None] | None:
    amts: list[int] = [
        m for a in re.findall(r"\$[\d,]+(?:\.\d{2})?", label) if (m := parse_money(a)) is not None
    ]
    low = label.lower()
    if re.search(r"less than|under|below", low) and len(amts) == 1:
        return 0, amts[0] - 1
    if re.search(r"and over|or more|\+$|and above", low) and len(amts) == 1:
        return amts[0], None
    if len(amts) == 2:
        return amts[0], amts[1]
    return None


def balance_tiers(lines: list[str]) -> tuple[list[tuple[int, int | None, Decimal]], str] | None:
    """Rows after an "Account Balance Rate APY" header (rate sheets): [(min cents, max cents or None, APY)], first
    row as evidence. The first table on the page is the account's standard rate."""
    for i, ln in enumerate(lines):
        if not _TIER_HEADER.match(ln.strip()):
            continue
        rows: list[tuple[int, int | None, Decimal]] = []
        first = None
        for nxt in lines[i + 1 : i + 20]:
            m = _TIER_ROW.match(nxt.strip())
            if not m or (b := _tier_bounds(m.group("lab"))) is None:
                break
            rows.append((b[0], b[1], Decimal(m.group("apy"))))
            first = first or nxt.strip()
        if rows and first:
            return rows, first
    return None


_SENT = re.compile(r"(?<=[a-z0-9)][.!?])\s+")
_WORD_COUNT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_INTRO_WAIVER = re.compile(
    r"(?:waived|not\s+be\s+charged\s+a\s+monthly\s+(?:service|maintenance)\s+fee)\s+for\s+(?P<least>at\s+least\s+)?"
    r"the\s+first\s+(?P<n>\d|one|two|three|four|five|six)\s+(?P<unit>statement\s+periods?|statement\s+cycles?|months?)",
    re.I,
)


def intro_fee_waiver(lines: list[str]) -> tuple[dict[str, object], str] | None:
    """A new-account fee waiver ("the $12 Monthly Maintenance Fee is waived for the first two statement periods",
    "will not be charged a Monthly Service Fee for at least the first two statement periods"): {count, unit,
    qualifier, text}. The unit is kept as stated (a statement period is never read as a month); when the page states
    both, the statement-period wording (the account terms) is used."""
    found: list[tuple[dict[str, object], str]] = []
    for ln in lines:
        for sent in _SENT.split(ln):
            if m := _INTRO_WAIVER.search(sent):
                n = m.group("n").lower()
                unit = m.group("unit").lower()
                found.append(
                    (
                        {
                            "count": int(n) if n.isdigit() else _WORD_COUNT[n],
                            "unit": "month" if unit.startswith("month") else "statement_period",
                            "qualifier": "at_least" if m.group("least") else "exact",
                            "text": sent.strip(),
                        },
                        sent.strip(),
                    )
                )
    if not found:
        return None
    return next((f for f in found if f[0]["unit"] == "statement_period"), found[0])


_ACCOUNT_ELIGIBILITY = re.compile(
    r"\b(?:currently\s+accepting\s+applications\s+from|only\s+available\s+to|available\s+only\s+to|"
    r"to\s+be\s+eligible\s+to\s+open)\b",
    re.I,
)


def account_eligibility(lines: list[str]) -> str | None:
    """Who may open the account, in the page's words ("We are currently accepting applications from Card Members with
    a U.S. Basic Consumer Card, ..."). Only the bank's own statement; never a rule from elsewhere."""
    for ln in lines:
        for sent in _SENT.split(ln):
            if _ACCOUNT_ELIGIBILITY.search(sent) and len(sent) < 400:
                return sent.strip().lstrip("*†‡ ")
    return None


_BONUS_INELIGIBLE = re.compile(
    r"\bnot\s+(?:be\s+)?eligible\s+(?:for|to\s+receive)\s+(?:this|the|a)\s+(?:welcome\s+)?bonus\b", re.I
)


def bonus_eligibility(lines: list[str]) -> str | None:
    """The page's own exclusion for the account bonus ("You are not eligible for this Welcome Bonus if you have an
    existing Rewards Checking Account or previously had a Rewards Checking Account.")."""
    for ln in lines:
        for sent in _SENT.split(ln):
            if _BONUS_INELIGIBLE.search(sent) and len(sent) < 400:
                return sent.strip()
    return None


_FOOTNOTE_TIER = re.compile(
    r"A\s+rate\s+of\s+(?P<apy>\d{1,2}\.\d{1,3})%\s+(?:Annual\s+Percentage\s+Yield\s+\(APY\)|APY)\s+applies\s+to\s+"
    r"accounts\s+with\s+balances\s+(?:between\s+(?P<lo>\$[\d,]+(?:\.\d{2})?)\s*(?:–|-|to)\s*(?P<hi>\$[\d,]+(?:\.\d{2})?)|"
    r"of\s+(?P<min>\$[\d,]+(?:\.\d{2})?)\s+or\s+more)",
    re.I,
)


def footnote_apy_tiers(lines: list[str]) -> tuple[list[tuple[int, int | None, Decimal]], str] | None:
    """Tiered checking APYs stated in a footnote ("A rate of 0.001% Annual Percentage Yield (APY) applies to accounts
    with balances between $0–$24,999.99. A rate of 0.005% APY applies to accounts with balances of $25,000.00 or
    more."): [(min cents, max cents or None, APY)] and the footnote line as evidence. Only a complete ladder (starting
    at $0 and ending open) is returned."""
    for ln in lines:
        rows: list[tuple[int, int | None, Decimal]] = []
        for m in _FOOTNOTE_TIER.finditer(ln):
            if m.group("min"):
                lo = parse_money(m.group("min"))
                if lo is None:
                    return None
                rows.append((lo, None, Decimal(m.group("apy"))))
            else:
                lo, hi = parse_money(m.group("lo")), parse_money(m.group("hi"))
                if lo is None or hi is None:
                    return None
                rows.append((lo, hi, Decimal(m.group("apy"))))
        if rows:
            if rows[0][0] != 0 or rows[-1][1] is not None:
                return None
            return rows, ln.strip()
    return None
