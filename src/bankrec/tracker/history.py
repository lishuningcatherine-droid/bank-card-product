"""History labels (DESIGN §27.5).

"Usual level" = the median of the public offers this site recorded for the card in the last 24 months, per reward
unit. Comparative labels need at least 3 records spanning at least 12 months; otherwise "not enough history". Every
label says it is about the history recorded on this site, and whether third-party records were counted.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bankrec.tracker import config


@dataclass(frozen=True)
class Record:
    amount: int
    unit: str
    valid_from: datetime
    valid_to: datetime | None
    official: bool
    current: bool = False


def _months(a: datetime, b: datetime) -> float:
    return (b - a).days / 30.4375


def label(records: list[Record], now: datetime, *, official_only: bool = False) -> dict[str, Any]:
    cfg = config.settings()["history"]
    current = next((r for r in records if r.current), None)
    out: dict[str, Any] = {
        "code": "insufficient_history",
        "text": "Not enough history recorded on this site yet.",
        "records": 0,
        "coverage_months": 0,
        "median": None,
        "official_only": official_only,
    }
    if current is None:
        return out
    since = now - timedelta(days=int(cfg["window_months"]) * 30.4375)
    past = [
        r
        for r in records
        if not r.current
        and r.unit == current.unit
        and (r.valid_to is None or r.valid_to >= since)
        and (r.official or not official_only)
    ]
    pool = [*past, current]
    first = min(r.valid_from for r in pool)
    coverage = _months(max(first, since), now)
    out.update(records=len(pool), coverage_months=round(coverage, 1))
    if len(pool) < int(cfg["min_records"]) or coverage < float(cfg["min_coverage_months"]):
        out["text"] = (
            f"Not enough history recorded on this site yet ({len(pool)} record(s) over {coverage:.0f} month(s); "
            f"comparisons need {cfg['min_records']} records over {cfg['min_coverage_months']} months)."
        )
        return out
    med = statistics.median(r.amount for r in pool)
    hi = max(r.amount for r in past) if past else current.amount
    recent = [
        r for r in past if (r.valid_to or now) >= now - timedelta(days=int(cfg["recent_months"]) * 30.4375)
    ]
    out["median"] = med
    basis = (
        ""
        if official_only
        else " (including third-party records)"
        if any(not r.official for r in pool)
        else ""
    )
    if current.amount > hi:
        out.update(
            code="all_time_high",
            text=f"In the history recorded on this site{basis}, this is the highest offer.",
        )
    elif current.amount > med:
        if recent and current.amount >= max(r.amount for r in recent):
            out.update(
                code="recent_high",
                text=f"In the history recorded on this site{basis}, this is higher than usual and the highest in the last {cfg['recent_months']} months.",
            )
        else:
            out.update(
                code="above_usual",
                text=f"In the history recorded on this site{basis}, this is better than the usual level.",
            )
    elif current.amount < med:
        out.update(
            code="below_usual",
            text=f"In the history recorded on this site{basis}, this is below the usual level.",
        )
    else:
        out.update(
            code="usual", text=f"In the history recorded on this site{basis}, this is the usual level."
        )
    return out
