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

    # AMAZON.DATE supplies normalized ISO values rather than the words Alexa
    # heard. Accept those values here so interaction-model dates use the same
    # publishedFrom/publishedTo path as free-form temporal phrases.
    iso_day = re.search(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b", text)
    if iso_day:
        start = datetime(
            int(iso_day.group("year")), int(iso_day.group("month")),
            int(iso_day.group("day")), tzinfo=tz,
        )
        end = (
            min(start + timedelta(days=1), current)
            if start.date() == current.date()
            else start + timedelta(days=1)
        )
        return TemporalRange(
            int(start.timestamp()), int(end.timestamp()),
            f"{start.day} {start.strftime('%B %Y')}",
            iso_day.start(), iso_day.end(),
        )

    iso_week = re.search(r"\b(?P<year>\d{4})-W(?P<week>\d{2})\b", text, re.IGNORECASE)
    if iso_week:
        start = datetime.combine(
            datetime.fromisocalendar(
                int(iso_week.group("year")), int(iso_week.group("week")), 1,
            ).date(),
            time.min,
            tzinfo=tz,
        )
        range_end = start + timedelta(days=7)
        end = min(range_end, current) if start <= current else range_end
        return TemporalRange(
            int(start.timestamp()), int(end.timestamp()),
            f"week {iso_week.group('week')} of {iso_week.group('year')}",
            iso_week.start(), iso_week.end(),
        )

    iso_month = re.search(r"\b(?P<year>\d{4})-(?P<month>\d{2})\b", text)
    if iso_month:
        start = datetime(
            int(iso_month.group("year")), int(iso_month.group("month")), 1,
            tzinfo=tz,
        )
        next_month = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12 else start.replace(month=start.month + 1)
        )
        return TemporalRange(
            int(start.timestamp()), int(
                (min(next_month, current) if start <= current else next_month).timestamp()
            ),
            start.strftime("%B %Y"), iso_month.start(), iso_month.end(),
        )

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
