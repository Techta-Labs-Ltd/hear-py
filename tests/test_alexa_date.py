from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils.alexa_date import AlexaDateRange


def test_exact_alexa_date_becomes_local_day_filter():
    result = AlexaDateRange.parse("2026-09-04", "Europe/London")
    assert result == {
        "publishedFrom": int(
            datetime(2026, 9, 4, tzinfo=ZoneInfo("Europe/London")).timestamp()
        ),
        "publishedTo": int(
            datetime(2026, 9, 5, tzinfo=ZoneInfo("Europe/London")).timestamp()
        ),
        "temporalOriginal": "4 September 2026",
    }


def test_alexa_week_becomes_monday_through_sunday_filter():
    result = AlexaDateRange.parse("2026-W35", "Europe/London")
    assert result["publishedFrom"] == int(
        datetime(2026, 8, 24, tzinfo=ZoneInfo("Europe/London")).timestamp()
    )
    assert result["publishedTo"] == int(
        datetime(2026, 8, 31, tzinfo=ZoneInfo("Europe/London")).timestamp()
    )
    assert result["temporalOriginal"] == "from 24 August to 30 August 2026"


def test_alexa_month_and_year_have_spoken_period_labels():
    assert AlexaDateRange.parse("2026-09", "Europe/London")["temporalOriginal"] == (
        "in September 2026"
    )
    assert AlexaDateRange.parse("2026", "Europe/London")["temporalOriginal"] == "in 2026"


def test_invalid_or_unbounded_alexa_date_is_ignored():
    assert AlexaDateRange.parse("PAST_REF", "Europe/London") == {}
    assert AlexaDateRange.parse("2026-W99", "Europe/London") == {}
    assert AlexaDateRange.parse("2026-09-04", "Invalid/Timezone") == {}
