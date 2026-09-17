from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class LaunchDecision:
    kind: Literal[
        "none",
        "town_capture",
        "continue_after_flag",
        "unfinished_playback",
        "pending_feedback",
        "ask_pending_feedback",
        "first_with_city",
        "first_without_city",
        "returning",
    ]
    user_name: str | None = None
    city: str | None = None
    locality: str | None = None


class LaunchPolicy:
    @staticmethod
    def user_name(store: dict) -> str | None:
        return str(store.get("userName") or store.get("fullName") or "").strip() or None

    @classmethod
    def protected(cls, store: dict) -> LaunchDecision:
        user_name = cls.user_name(store)
        if store.get("onboardingStage") == "confirm_town_for_community":
            return LaunchDecision("town_capture", user_name=user_name)
        if store.get("awaitingContinueAfterFlag"):
            return LaunchDecision("continue_after_flag", user_name=user_name)
        return LaunchDecision("none", user_name=user_name)

    @classmethod
    def pending(cls, store: dict, *, has_unfinished_playback: bool) -> LaunchDecision:
        user_name = cls.user_name(store)
        if has_unfinished_playback:
            return LaunchDecision("unfinished_playback", user_name=user_name)
        if store.get("awaitingFeedback") and store.get("pendingFeedback"):
            return LaunchDecision("pending_feedback", user_name=user_name)
        if store.get("awaitingFeedback") and (
            store.get("feedbackContentTitle") or store.get("feedbackPromptText")
        ):
            return LaunchDecision("ask_pending_feedback", user_name=user_name)
        return LaunchDecision("none", user_name=user_name)

    @classmethod
    def welcome(cls, store: dict) -> LaunchDecision:
        user_name = cls.user_name(store)
        locality = str(store.get("locality") or "").strip() or None
        city = str(store.get("userCity") or locality or "").strip() or None
        is_first_time = store.get("playCount", 0) == 0 and not store.get("lastToken")
        if is_first_time and city:
            return LaunchDecision(
                "first_with_city", user_name=user_name, city=city, locality=locality
            )
        if is_first_time:
            return LaunchDecision("first_without_city", user_name=user_name, locality=locality)
        return LaunchDecision("returning", user_name=user_name, locality=locality)
