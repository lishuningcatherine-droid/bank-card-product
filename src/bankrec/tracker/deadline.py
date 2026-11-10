"""Campaign start and end moments, in US Eastern time (DESIGN §27.3).

A deadline keeps exactly what the issuer stated: the date, the time only when a time is stated (never filled in as
23:59), the time zone it was stated in, and the sentence it came from. Unknown stays unknown.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_TZ = {
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "eastern": "America/New_York",
    "eastern time": "America/New_York",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "central": "America/Chicago",
    "central time": "America/Chicago",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "mountain": "America/Denver",
    "mountain time": "America/Denver",
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "pacific time": "America/Los_Angeles",
}
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
_DATE = (
    r"(?:(?P<mon>January|February|March|April|May|June|July|August|September|October|November|December)\.?\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})|(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{2,4}))"
)
_TIME = (
    r"(?:\s*(?:at|by|,)?\s*(?P<h>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ap>[ap])\.?\s?m\.?"
    r"(?:\s*\(?(?P<tz>E[SD]?T|C[SD]?T|M[SD]?T|P[SD]?T|Eastern(?: Time)?|Central(?: Time)?|Mountain(?: Time)?|"
    r"Pacific(?: Time)?)\)?)?)?"
)
_END_CUE = re.compile(
    r"(?:offer|promotion|this offer|application)s?\s+(?:ends?|expires?|must be (?:submitted|received) by|valid through)"
    r"|\b(?:apply|applications? (?:must be )?(?:received|submitted)|open (?:your|an|a new) account)\s+by\b"
    r"|\bexpires?\s+on\b|\bends?\s+on\b|\bvalid (?:through|until)\b",
    re.IGNORECASE,
)
_START_CUE = re.compile(r"\b(?:starting|beginning|available (?:from|starting)|on or after|effective)\b", re.I)


def _date_of(m: re.Match[str]) -> date:
    if m.group("mon"):
        return date(int(m.group("year")), _MONTHS[m.group("mon").lower()], int(m.group("day")))
    y = int(m.group("y"))
    return date(y + 2000 if y < 100 else y, int(m.group("m")), int(m.group("d")))


def moment(text: str | None, cue: re.Pattern[str] = _END_CUE) -> dict[str, Any] | None:
    """The first date introduced by ``cue`` in ``text``: {date, time (HH:MM, ET) or None, time_known, stated_tz,
    stated_date_text, text (the sentence)}. Times stated in another U.S. zone are converted to ET."""
    if not text:
        return None
    for sentence in re.split(r"(?<![ap]\.m\.)(?<=[.!?])\s+(?=[A-Z])", text):
        for c in cue.finditer(sentence):
            m = re.compile(_DATE + _TIME, re.IGNORECASE).search(sentence, c.end())
            if not m or m.start() - c.end() > 40:
                continue
            d = _date_of(m)
            out: dict[str, Any] = {
                "date": d.isoformat(),
                "time": None,
                "time_known": False,
                "stated_tz": None,
                "stated_date_text": m.group(0).strip(" ,"),
                "text": sentence.strip(),
            }
            if m.group("h"):
                h = int(m.group("h")) % 12 + (12 if m.group("ap").lower() == "p" else 0)
                mi = int(m.group("min") or 0)
                tzname = (m.group("tz") or "").lower()
                zone = ZoneInfo(_TZ.get(tzname, "America/New_York")) if tzname else None
                if zone is None:
                    # a time with no zone: kept as stated, flagged; it is not assumed to be Eastern
                    out.update(time=f"{h:02d}:{mi:02d}", time_known=True, stated_tz=None)
                else:
                    local = datetime.combine(d, time(h, mi), tzinfo=zone).astimezone(ET)
                    out.update(
                        date=local.date().isoformat(),
                        time=local.strftime("%H:%M"),
                        time_known=True,
                        stated_tz=m.group("tz"),
                    )
            return out
    return None


def end_from_offer(verbatim: str | None, expiration: date | None, open_by: date | None) -> dict[str, Any]:
    """The campaign's end as the pipeline read it (``expiration_date`` / ``open_by_date``) with the sentence that
    states it; unknown when neither is stated. ``confirmed`` = stated on an official page."""
    stated = moment(verbatim)
    d = expiration or open_by
    if d is None and stated is None:
        return unknown()
    if stated is not None and (d is None or stated["date"] == d.isoformat()):
        return {**stated, "confirmed": True}
    assert d is not None
    return {
        "date": d.isoformat(),
        "time": None,
        "time_known": False,
        "stated_tz": None,
        "stated_date_text": None,
        "text": None,
        "confirmed": True,
    }


def unknown() -> dict[str, Any]:
    return {
        "date": None,
        "time": None,
        "time_known": False,
        "stated_tz": None,
        "stated_date_text": None,
        "text": None,
        "confirmed": False,
    }


def instant(m: dict[str, Any] | None) -> datetime | None:
    """The moment a deadline passes, or None when the date is unknown. With no stated time the whole stated day
    counts (it passes at the start of the next ET day), but no time is ever displayed or invented."""
    if not m or not m.get("date"):
        return None
    d = date.fromisoformat(m["date"])
    if m.get("time_known") and m.get("time"):
        hh, mm = (int(x) for x in m["time"].split(":"))
        return datetime.combine(d, time(hh, mm), tzinfo=ET)
    return datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=ET)


def label(m: dict[str, Any] | None) -> str:
    """ "Deadline: 2026-12-05 23:59 ET" | "Deadline 2026-12-05 (time not published)" | "Deadline unknown"."""
    if not m or not m.get("date"):
        return "Deadline unknown"
    if m.get("time_known") and m.get("time"):
        tz = "ET" if m.get("stated_tz") is not None else "(time zone not stated)"
        return f"Deadline: {m['date']} {m['time']} {tz}"
    return f"Deadline {m['date']} (time not published)"
