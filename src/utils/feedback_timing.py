from __future__ import annotations

from config import settings


def feedback_trigger_ms(duration_secs) -> int | None:
    """Calculate the millisecond offset at which to trigger a feedback prompt."""
    if not isinstance(duration_secs, (int, float)) or duration_secs <= 0:
        return None
    threshold = settings.HEAR_FEEDBACK_SHORT_THRESHOLD_SECS or 30
    ratio = (settings.HEAR_FEEDBACK_SHORT_RATIO or 0.6) if duration_secs < threshold else (settings.HEAR_FEEDBACK_RATIO or 0.7)
    return int(duration_secs * 1000 * ratio)


def feedback_progress_report_options(duration_secs) -> dict:
    """Build the progress report delay/interval options for the AudioPlayer directive."""
    delay_ms = feedback_trigger_ms(duration_secs)
    if delay_ms is None:
        fallback = settings.feedback_trigger_ms or 90000
        return {
            "progressReportDelayInMilliseconds": fallback,
            "progressReportIntervalInMilliseconds": fallback * 10,
        }
    return {
        "progressReportDelayInMilliseconds": delay_ms,
        "progressReportIntervalInMilliseconds": max(delay_ms * 2, 86400000),
    }
