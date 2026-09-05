from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from src.alexa.context import RequestContext
from src.models.user import User


class OnboardingStage(StrEnum):
    ASK_PERMISSION = "ask_permission"
    ASK_TOWN = "ask_town"
    AWAIT_LOCATION_CONFIRMATION = "await_location_confirm"


@dataclass(frozen=True, slots=True)
class LocationCandidate:
    city: str
    locality: str | None = None
    country_code: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LocationCandidate:
        return cls(
            city=str(value["city"]),
            locality=value.get("locality"),
            country_code=value.get("countryCode"),
            postal_code=value.get("postalCode"),
            latitude=value.get("latitude"),
            longitude=value.get("longitude"),
            source=value.get("source"),
        )

    def to_store(self) -> dict[str, Any]:
        values = {
            "city": self.city,
            "locality": self.locality,
            "countryCode": self.country_code,
            "postalCode": self.postal_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
        }
        return {key: value for key, value in values.items() if value is not None}


class OnboardingState:
    __slots__ = ("_user",)

    def __init__(self, store: User) -> None:
        self._user = store

    def snapshot(self, handler_input) -> dict:
        return self._user.snapshot(handler_input)

    def stage_permission(self, handler_input, *, reliable: bool) -> dict:
        changes = {"onboardingStage": OnboardingStage.ASK_PERMISSION}
        if reliable:
            changes["_requiresReliableSave"] = True
        return self._apply(
            handler_input,
            changes,
            session={"onboardingStage": OnboardingStage.ASK_PERMISSION},
        )

    def start_town_capture(
        self, handler_input, *, reliable: bool, reset_resolver_failures: bool
    ) -> dict:
        changes = {
            "onboardingStage": OnboardingStage.ASK_TOWN,
            "onboardingTownAttempts": 0,
        }
        if reliable:
            changes["_requiresReliableSave"] = True
            changes["onboardingRetries"] = 0
        if reset_resolver_failures:
            changes["onboardingTownResolverFailures"] = 0
        return self._apply(
            handler_input,
            changes,
            session={"onboardingStage": OnboardingStage.ASK_TOWN},
        )

    def save_town_attempts(self, handler_input, attempts: int) -> dict:
        return self._user.update(handler_input, {"onboardingTownAttempts": attempts})

    def save_resolver_failures(self, handler_input, failures: int) -> dict:
        return self._user.update(
            handler_input,
            {
                "onboardingStage": OnboardingStage.ASK_TOWN,
                "onboardingTownResolverFailures": failures,
            },
        )

    def reset_resolver_failures(self, handler_input) -> dict:
        return self._user.update(handler_input, {"onboardingTownResolverFailures": 0})

    def await_confirmation(
        self, handler_input, candidate: LocationCandidate, *, reset_attempts: bool
    ) -> dict:
        pending = candidate.to_store()
        changes = {
            "pendingLocationConfirm": pending,
            "awaitingLocationConfirm": True,
            "onboardingStage": OnboardingStage.AWAIT_LOCATION_CONFIRMATION,
            "_requiresReliableSave": True,
        }
        if reset_attempts:
            changes["onboardingTownAttempts"] = 0
        return self._apply(
            handler_input,
            changes,
            session={
                "onboardingStage": OnboardingStage.AWAIT_LOCATION_CONFIRMATION,
                "awaitingLocationConfirm": True,
                "pendingLocationConfirm": pending,
            },
        )

    def cache_coordinates(self, handler_input, candidate: LocationCandidate) -> dict:
        return self._user.update(
            handler_input,
            {
                "latitude": candidate.latitude,
                "longitude": candidate.longitude,
                "_requiresReliableSave": True,
            },
        )

    def complete_location(
        self,
        handler_input,
        candidate: LocationCandidate,
        *,
        offer_community_playback: bool,
        preserve_postal_code: bool,
    ) -> dict:
        locality = candidate.locality or candidate.city
        changes = {
            "deviceCountryCode": candidate.country_code,
            "latitude": candidate.latitude,
            "longitude": candidate.longitude,
            "onboardingComplete": True,
            "onboardingStage": None,
            "onboardingTownAttempts": 0,
            "onboardingTownResolverFailures": 0,
            "locationSource": candidate.source or "manual",
            "localityResolvedAt": int(time.time() * 1000),
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
            "_requiresReliableSave": True,
        }
        if candidate.city:
            changes.update({"userCity": candidate.city, "locality": locality})
        if preserve_postal_code:
            current = self.snapshot(handler_input)
            changes["devicePostalCode"] = candidate.postal_code or current.get("devicePostalCode")
        session = {
            "onboardingStage": None,
            "onboardingComplete": True,
            "awaitingLocationConfirm": False,
        }
        if candidate.city:
            session.update({"userCity": candidate.city, "locality": locality})
        if offer_community_playback:
            changes["awaitingCommunityPlayback"] = True
            session["awaitingCommunityPlayback"] = True
        return self._apply(handler_input, changes, session=session)

    def clear_confirmation(self, handler_input) -> dict:
        changes = {
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
            "onboardingStage": None,
        }
        return self._apply(handler_input, changes, session=changes)

    def complete_without_location(self, handler_input, *, reliable: bool) -> dict:
        changes = {
            "onboardingStage": None,
            "onboardingTownAttempts": 0,
            "onboardingTownResolverFailures": 0,
            "onboardingComplete": True,
            "awaitingLocationConfirm": False,
            "pendingLocationConfirm": None,
        }
        if reliable:
            changes["_requiresReliableSave"] = True
        return self._apply(
            handler_input,
            changes,
            session={"onboardingStage": None, "awaitingLocationConfirm": False},
        )

    def request_location_change(self, handler_input) -> dict:
        return self._user.update(
            handler_input,
            {"onboardingStage": OnboardingStage.ASK_TOWN, "onboardingTownAttempts": 0},
        )

    def _apply(self, handler_input, changes: dict, *, session: dict | None = None) -> dict:
        updated = self._user.update(handler_input, changes)
        if session:
            attributes = dict(RequestContext.session(handler_input) or {})
            attributes.update(session)
            RequestContext.replace_session(handler_input, attributes)
        return updated


class OnboardingService:
    __slots__ = ("_onboarding",)

    def __init__(self, onboarding: OnboardingState) -> None:
        self._onboarding = onboarding

    def snapshot(self, handler_input) -> dict:
        return self._onboarding.snapshot(handler_input)

    def ask_permission(self, handler_input) -> dict:
        return self._onboarding.stage_permission(handler_input, reliable=True)

    def keep_permission_pending(self, handler_input) -> dict:
        return self._onboarding.stage_permission(handler_input, reliable=False)

    def begin_town_capture(self, handler_input) -> dict:
        return self._onboarding.start_town_capture(
            handler_input, reliable=False, reset_resolver_failures=True
        )

    def decline_permission(self, handler_input) -> dict:
        return self._onboarding.start_town_capture(
            handler_input, reliable=True, reset_resolver_failures=False
        )

    def request_location_change(self, handler_input) -> dict:
        return self._onboarding.request_location_change(handler_input)

    def record_town_attempt(self, handler_input, current: dict) -> int:
        attempts = int(current.get("onboardingTownAttempts") or 0) + 1
        self._onboarding.save_town_attempts(handler_input, attempts)
        return attempts

    def reset_resolver_failures(self, handler_input) -> dict:
        return self._onboarding.reset_resolver_failures(handler_input)

    def record_resolver_failure(self, handler_input, current: dict) -> int:
        failures = int(current.get("onboardingTownResolverFailures") or 0) + 1
        self._onboarding.save_resolver_failures(handler_input, failures)
        return failures

    def stage_confirmation(
        self, handler_input, match: dict, *, reset_attempts: bool = False
    ) -> dict:
        return self._onboarding.await_confirmation(
            handler_input,
            LocationCandidate.from_mapping(match),
            reset_attempts=reset_attempts,
        )

    def cache_coordinates(self, handler_input, match: dict) -> dict:
        return self._onboarding.cache_coordinates(
            handler_input,
            LocationCandidate.from_mapping({**match, "city": match.get("city") or ""}),
        )

    def complete_location(
        self,
        handler_input,
        match: dict,
        *,
        offer_community_playback: bool = False,
        preserve_postal_code: bool = False,
    ) -> dict:
        return self._onboarding.complete_location(
            handler_input,
            LocationCandidate.from_mapping(match),
            offer_community_playback=offer_community_playback,
            preserve_postal_code=preserve_postal_code,
        )

    def clear_invalid_confirmation(self, handler_input) -> dict:
        return self._onboarding.clear_confirmation(handler_input)

    def complete_without_location(self, handler_input, *, reliable: bool = True) -> dict:
        return self._onboarding.complete_without_location(handler_input, reliable=reliable)

    def location_not_found(self, handler_input) -> dict:
        return self._onboarding.start_town_capture(
            handler_input, reliable=True, reset_resolver_failures=True
        )
