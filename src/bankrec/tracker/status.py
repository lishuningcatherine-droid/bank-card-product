"""Campaign status machine (DESIGN §27.3).

active → ending_soon (confirmed deadline within N days) → expired (confirmed deadline passed)
any → pending_verification (a good capture of the official page no longer shows it; never "ended" by itself)
any → stale (N failed checks in a row, or no successful check for D days; never "ended" by itself)
expired / withdrawn are set automatically only for a passed confirmed deadline; anything else needs a reviewer.
A single failed check changes nothing but the failure count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bankrec.tracker import config, deadline

STATUSES = ("active", "ending_soon", "expired", "withdrawn", "pending_verification", "stale")
FINAL = {"expired", "withdrawn"}
LABEL = {
    "active": "Active",
    "ending_soon": "Ending soon",
    "expired": "Expired",
    "withdrawn": "Withdrawn",
    "pending_verification": "Needs verification",
    "stale": "Data out of date",
}


def compute(
    current: str | None,
    *,
    end: dict[str, Any] | None,
    now: datetime,
    last_verified_at: datetime | None,
    consecutive_failures: int,
    not_seen: bool,
    settings: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """(status, reason). ``not_seen`` = the last successful capture of the official page did not show the offer."""
    cfg = settings or config.settings()
    if current in FINAL:
        return current, "kept: set by a reviewer or a passed confirmed deadline"
    ends = deadline.instant(end) if end and end.get("confirmed") else None
    if ends is not None and ends <= now:
        return "expired", f"the confirmed deadline has passed ({deadline.label(end)})"
    if not_seen:
        return (
            "pending_verification",
            "not shown on the official page at the last successful check; not treated as ended until confirmed",
        )
    stale = cfg["stale"]
    if consecutive_failures >= int(stale["consecutive_failures"]):
        return "stale", f"{consecutive_failures} checks in a row failed; the offer is not treated as ended"
    if last_verified_at is not None and now - last_verified_at > timedelta(
        days=int(stale["days_without_success"])
    ):
        days = (now - last_verified_at).days
        return "stale", f"no successful check for {days} days; the offer is not treated as ended"
    if ends is not None and ends - now <= timedelta(days=int(cfg["ending_soon_days"])):
        return (
            "ending_soon",
            f"confirmed deadline within {cfg['ending_soon_days']} days ({deadline.label(end)})",
        )
    return "active", "shown on the official page at the last successful check"
