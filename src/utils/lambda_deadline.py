from __future__ import annotations

import os

from config import settings
from src.utils.skill_request import get_request_type


def _is_lambda() -> bool:
    """Check whether running in an AWS Lambda environment."""
    return (os.environ.get("AWS_EXECUTION_ENV") or "").startswith("AWS_Lambda_")


def get_lambda_remaining_ms(handler_input=None) -> int:
    """Get the remaining invocation time in milliseconds."""
    if not _is_lambda():
        return 30000
    try:
        aws_context = getattr(handler_input, "context", None) if handler_input else None
        if aws_context:
            remaining = aws_context.get_remaining_time_in_millis()
            if remaining:
                return int(remaining)
    except Exception:
        pass
    return 8000


def compute_search_timeout_ms(handler_input, reserve_ms: int = 700) -> int:
    """Compute an appropriate API timeout for search requests."""
    remaining = get_lambda_remaining_ms(handler_input)
    if remaining <= 0:
        return 8000
    cap = min(max(remaining - reserve_ms - 500, 1000), 10000)
    return max(cap, 2000)


def compute_bounded_api_timeout_ms(handler_input, reserve_ms: int = 400) -> int:
    """Compute a bounded API timeout for general requests."""
    remaining = get_lambda_remaining_ms(handler_input)
    if remaining <= 0:
        return 6000
    return max(min(remaining - reserve_ms - 500, 6000), 1000)


def api_options(handler_input) -> int:
    """Bounded per-call API timeout (ms) derived from the remaining Lambda budget.

    Passed as the ``timeout_ms`` argument to API helpers such as
    ``get_content_by_id`` so single content look-ups stay within the invocation
    deadline.
    """
    return compute_bounded_api_timeout_ms(handler_input)


def persistence_load_budget_ms(handler_input) -> int:
    """Get the ms budget remaining for persistence load operations."""
    remaining = get_lambda_remaining_ms(handler_input)
    if remaining <= 1500:
        return 0
    return max(min(remaining - 1200, 4000), 200)


def persistence_save_budget_ms(handler_input) -> int:
    """Get the ms budget remaining for persistence save operations."""
    remaining = get_lambda_remaining_ms(handler_input)
    if remaining <= 800:
        return 0
    return max(min(remaining - 600, 2000), 100)


def should_skip_persistence_load(handler_input) -> bool:
    """Check whether persistence load should be skipped due to time pressure."""
    rtype = get_request_type(handler_input)
    if rtype in ("AudioPlayer.PlaybackStarted", "AudioPlayer.PlaybackProgressReport"):
        return get_lambda_remaining_ms(handler_input) < 900
    if rtype in ("AudioPlayer.PlaybackStopped", "AudioPlayer.PlaybackFailed"):
        return get_lambda_remaining_ms(handler_input) < 700
    return False


def requires_reliable_persistence_load(handler_input) -> bool:
    """Check whether the request requires a reliable persistence load."""
    rtype = get_request_type(handler_input)
    return rtype in ("LaunchRequest", "IntentRequest")


def requires_reliable_persistence_save(handler_input) -> bool:
    """Check whether the session store requires a reliable persistence save."""
    try:
        attrs = getattr(handler_input.attributes_manager, "request_attributes", {}) or {}
        store = attrs.get("_store") or {}
        return bool(store.get("_requiresReliableSave"))
    except Exception:
        return False


def has_budget_for_api(handler_input, reserve_ms: int = 1000) -> bool:
    """Check whether there is enough remaining time to make an API call."""
    return get_lambda_remaining_ms(handler_input) > reserve_ms + 2000


def should_refresh_browse_on_launch(handler_input) -> bool:
    """Check whether browse data should be refreshed on launch."""
    return settings.HEAR_REFRESH_BROWSE_ON_LAUNCH


def should_block_on_launch_flush(handler_input) -> bool:
    """Check whether we should block waiting for a launch playback flush."""
    remaining = get_lambda_remaining_ms(handler_input)
    return remaining > 5000


def launch_background_work_budget_ms(handler_input) -> int:
    """Get the budget in ms for background work during launch."""
    remaining = get_lambda_remaining_ms(handler_input)
    if remaining <= 4500:
        return 0
    return remaining - 4000
