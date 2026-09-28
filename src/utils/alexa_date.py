from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AlexaDateRange:
    _SPOKEN_RELATIVE = re.compile(
        r"\b(?P<period>today|yesterday|this\s+week|last\s+week|this\s+month|last\s+month|this\s+year|last\s+year)\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _label(start: datetime, end: datetime) -> str:
        last = end - timedelta(days=1)
        if end - start <= timedelta(days=1):
            return f"{start.day} {start.strftime('%B')} {start.year}"
        if start.year == last.year:
            return f"from {start.day} {start.strftime('%B')} to {last.day} {last.strftime('%B')} {last.year}"
        return (
            f"from {start.day} {start.strftime('%B')} {start.year} "
            f"to {last.day} {last.strftime('%B')} {last.year}"
        )

    @staticmethod
    def _result(start: datetime, end: datetime, label: str | None = None) -> dict:
        return {
            "publishedFrom": int(start.timestamp()),
            "publishedTo": int(end.timestamp()),
            "temporalOriginal": label or AlexaDateRange._label(start, end),
        }

    @staticmethod
    def _month_start(value: datetime) -> datetime:
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _next_month_start(value: datetime) -> datetime:
        return (
            value.replace(year=value.year + 1, month=1, day=1)
            if value.month == 12
            else value.replace(month=value.month + 1, day=1)
        )

    @classmethod
    def extract_spoken(
        cls,
        value: object,
        timezone_name: str,
        *,
        now: datetime | None = None,
    ) -> tuple[dict, str]:
        text = " ".join(str(value or "").split())
        match = cls._SPOKEN_RELATIVE.search(text)
        if not text or not match:
            return {}, text
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return {}, text
        current = now.astimezone(zone) if isinstance(now, datetime) else datetime.now(zone)
        day = current.replace(hour=0, minute=0, second=0, microsecond=0)
        period = " ".join(match.group("period").casefold().split())

        if period == "today":
            start, end = day, day + timedelta(days=1)
        elif period == "yesterday":
            start, end = day - timedelta(days=1), day
        elif period in {"this week", "last week"}:
            this_week = day - timedelta(days=day.weekday())
            if period == "this week":
                start, end = this_week, this_week + timedelta(days=7)
            else:
                start, end = this_week - timedelta(days=7), this_week
        elif period in {"this month", "last month"}:
            this_month = cls._month_start(day)
            if period == "this month":
                start, end = this_month, cls._next_month_start(this_month)
            else:
                end = this_month
                start = cls._month_start(this_month - timedelta(days=1))
        else:
            this_year = day.replace(month=1, day=1)
            if period == "this year":
                start, end = this_year, this_year.replace(year=this_year.year + 1)
            else:
                end = this_year
                start = this_year.replace(year=this_year.year - 1)

        remainder = " ".join(
            f"{text[:match.start()]} {text[match.end():]}".split()
        )
        return cls._result(start, end, period), remainder

    @staticmethod
    def _bounds(value: str, zone: ZoneInfo) -> tuple[datetime, datetime] | None:
        exact = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
        if exact:
            year_text, month_text, day_text = exact.groups()
            start = datetime(
                int(year_text), int(month_text), int(day_text), tzinfo=zone
            )
            return start, start + timedelta(days=1)
        weekend = re.fullmatch(r"(\d{4})-W(\d{2})-WE", value)
        if weekend:
            start = datetime.fromisocalendar(
                int(weekend.group(1)), int(weekend.group(2)), 6
            ).replace(tzinfo=zone)
            return start, start + timedelta(days=2)
        week = re.fullmatch(r"(\d{4})-W(\d{2})", value)
        if week:
            start = datetime.fromisocalendar(
                int(week.group(1)), int(week.group(2)), 1
            ).replace(tzinfo=zone)
            return start, start + timedelta(days=7)
        month_match = re.fullmatch(r"(\d{4})-(\d{2})", value)
        if month_match:
            year_text, month_text = month_match.groups()
            year_number, month_number = int(year_text), int(month_text)
            start = datetime(year_number, month_number, 1, tzinfo=zone)
            end = (
                datetime(year_number + 1, 1, 1, tzinfo=zone)
                if month_number == 12
                else datetime(year_number, month_number + 1, 1, tzinfo=zone)
            )
            return start, end
        year_match = re.fullmatch(r"(\d{4})", value)
        if year_match:
            year_number = int(year_match.group(1))
            return (
                datetime(year_number, 1, 1, tzinfo=zone),
                datetime(year_number + 1, 1, 1, tzinfo=zone),
            )
        return None
    @staticmethod
    def parse(value: object, timezone_name: str) -> dict:
        normalized = str(value or "").strip()
        if not normalized:
            return {}
        try:
            zone = ZoneInfo(timezone_name)
            if "/" in normalized:
                start_value, end_value = normalized.split("/", 1)
                start_bounds = AlexaDateRange._bounds(start_value, zone)
                end_bounds = AlexaDateRange._bounds(end_value, zone)
                if not start_bounds or not end_bounds:
                    return {}
                start, end = start_bounds[0], end_bounds[1]
                return AlexaDateRange._result(start, end)
            bounds = AlexaDateRange._bounds(normalized, zone)
        except (ValueError, ZoneInfoNotFoundError):
            return {}
        if not bounds:
            return {}
        start, end = bounds
        if re.fullmatch(r"\d{4}-\d{2}", normalized):
            return AlexaDateRange._result(start, end, f"in {start.strftime('%B %Y')}")
        if re.fullmatch(r"\d{4}", normalized):
            return AlexaDateRange._result(start, end, f"in {start.year}")
        return AlexaDateRange._result(start, end)
