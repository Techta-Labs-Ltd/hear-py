from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AlexaDateRange:
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
    def _bounds(value: str, zone: ZoneInfo) -> tuple[datetime, datetime] | None:
        exact = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
        if exact:
            start = datetime(*(int(part) for part in exact.groups()), tzinfo=zone)
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
        month = re.fullmatch(r"(\d{4})-(\d{2})", value)
        if month:
            year, month_number = (int(part) for part in month.groups())
            start = datetime(year, month_number, 1, tzinfo=zone)
            end = (
                datetime(year + 1, 1, 1, tzinfo=zone)
                if month_number == 12
                else datetime(year, month_number + 1, 1, tzinfo=zone)
            )
            return start, end
        year = re.fullmatch(r"(\d{4})", value)
        if year:
            year_number = int(year.group(1))
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
