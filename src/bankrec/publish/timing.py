from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def expiry_instant(expiration: date) -> datetime:
    """00:05 America/New_York on the day after the expiration date: the first moment the offer is expired."""
    return datetime.combine(expiration + timedelta(days=1), time(0, 5), ZoneInfo("America/New_York"))
