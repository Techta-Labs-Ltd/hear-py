from __future__ import annotations

import time
from dataclasses import dataclass

from config import settings


@dataclass(frozen=True, slots=True)
class RequestDeadline:
    expires_at: float

    @classmethod
    def from_context(cls, context, *, default_ms: int = 30000) -> RequestDeadline:
        remaining = getattr(context, "get_remaining_time_in_millis", None)
        budget_ms = int(remaining()) if callable(remaining) else default_ms
        return cls(time.monotonic() + max(budget_ms, 0) / 1000.0)

    def remaining_ms(self, reserve_ms: int = 0) -> int:
        return max(0, int((self.expires_at - time.monotonic()) * 1000) - reserve_ms)


class DeadlineBudget:
    @staticmethod
    def _is_lambda() -> bool:
        return settings.is_lambda

    @staticmethod
    def get_lambda_remaining_ms(handler_input=None) -> int:
        deadline = getattr(handler_input, "deadline", None)
        if isinstance(deadline, RequestDeadline):
            return deadline.remaining_ms()
        if not DeadlineBudget._is_lambda():
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

    @staticmethod
    def compute_search_timeout_ms(handler_input, reserve_ms: int = 700) -> int:
        configured = settings.api_timeout_ms or 8000
        return DeadlineBudget.outbound_timeout_ms(handler_input, configured, reserve_ms=reserve_ms)

    @staticmethod
    def outbound_timeout_ms(
        handler_input,
        configured_ms: int,
        *,
        reserve_ms: int = 800,
        minimum_ms: int = 100,
    ) -> int:
        configured = max(int(configured_ms or minimum_ms), minimum_ms)
        remaining = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        available = max(remaining - reserve_ms, 0)
        return min(configured, available)

    @staticmethod
    def resolver_timeout_ms(handler_input) -> int:
        return DeadlineBudget.outbound_timeout_ms(handler_input, settings.HEAR_RESOLVER_TIMEOUT_MS)

    @staticmethod
    def persistence_load_budget_ms(handler_input) -> int:
        remaining = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        if remaining <= 1500:
            return 0
        return max(min(remaining - 1200, 4000), 200)

    @staticmethod
    def persistence_save_budget_ms(handler_input) -> int:
        remaining = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        if remaining <= 800:
            return 0
        return max(min(remaining - 600, 2000), 100)

    @staticmethod
    def should_skip_persistence_load(request_type: str, remaining_ms: int) -> bool:
        if request_type in {
            "AudioPlayer.PlaybackStarted",
            "AudioPlayer.PlaybackProgressReportDelayPassed",
            "AudioPlayer.PlaybackProgressReportIntervalPassed",
        }:
            return remaining_ms < 900
        if request_type in (
            "AudioPlayer.PlaybackStopped",
            "AudioPlayer.PlaybackFailed",
        ):
            return remaining_ms < 700
        return False

    @staticmethod
    def requires_reliable_persistence_load(request_type: str) -> bool:
        return request_type in ("LaunchRequest", "IntentRequest")
