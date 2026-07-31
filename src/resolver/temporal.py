from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.resolver.models import TemporalRange

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

def _zone(name: str | None):
    try:
        return ZoneInfo(name or "Europe/London")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _range(text: str, start: datetime, end: datetime, match: re.Match) -> TemporalRange:
    return TemporalRange(
        int(start.timestamp()), int(end.timestamp()), match.group(0),
        match.start(), match.end(),
    )

def parse_temporal(
    text: str,
    timezone: str = "Europe/London",
    now: datetime | None = None,
) -> TemporalRange | None:
    tz = _zone(timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    today = datetime.combine(current.date(), time.min, tzinfo=tz)

    patterns = (
        (r"\byesterday(?:'s)?\b", lambda m: _range(text, today - timedelta(days=1), today, m)),
        (r"\btoday(?:'s)?\b", lambda m: _range(text, today, current, m)),
        (r"\blast week\b", lambda m: _range(
            text, today - timedelta(days=today.weekday() + 7),
            today - timedelta(days=today.weekday()), m,
        )),
        (r"\bthis week\b", lambda m: _range(
            text, today - timedelta(days=today.weekday()), current, m,
        )),
        (r"\blast month\b", lambda m: _range(
            text,
            (today.replace(day=1) - timedelta(days=1)).replace(day=1),
            today.replace(day=1), m,
        )),
    )
    for pattern, build in patterns:
        match = re.search(pattern, text)
        if match:
            return build(match)

    match = re.search(
        r"\b(?P<prep>from|since|on)\s+(?:(?P<last>last)\s+)?"
        r"(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
    )
    if not match:
        return None
    target = WEEKDAYS[match.group("day")]
    days_back = (today.weekday() - target) % 7
    if match.group("last"):
        days_back = days_back + 7 if days_back else 7
    start = today - timedelta(days=days_back)
    end = start + timedelta(days=1) if match.group("prep") == "on" else current
    return _range(text, start, end, match)
