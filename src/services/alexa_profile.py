from __future__ import annotations

import asyncio
import time

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.clients.alexa_settings import AlexaSettingsClient
from src.models.listener import Listener
from src.services.alexa_locality import AlexaLocalitySupport


class AlexaProfileModule:
    _PROFILE_TTL_MS = 24 * 60 * 60 * 1000
    _PROFILE_BACKOFF_MS = 5 * 60 * 1000


class AlexaProfilePolicy:
    @staticmethod
    def is_fresh(active: dict, now: int) -> bool:
        resolved_at = int(active.get("listenerProfileResolvedAt") or 0)
        has_name = AlexaLocalitySupport.has_any_profile_name(active)
        return bool(
            has_name
            and active.get("userEmail")
            and resolved_at
            and now - resolved_at < AlexaProfileModule._PROFILE_TTL_MS
        )

    @staticmethod
    def requests(active: dict) -> list[tuple[str, str]]:
        requests = []
        if not AlexaLocalitySupport.has_any_profile_name(active):
            requests.extend((("fullName", "Profile.name"), ("givenName", "Profile.givenName")))
        if not active.get("userEmail"):
            requests.append(("userEmail", "Profile.email"))
        return requests

    @staticmethod
    def availability(statuses: list[int], given_name_granted: bool) -> tuple[dict, bool]:
        saw_denied = any(status in (401, 403) for status in statuses)
        saw_empty = any(status == 204 for status in statuses)
        saw_missing_token = any(status == 0 for status in statuses)
        should_retry = (
            saw_denied
            or saw_missing_token
            or not given_name_granted
            and (saw_denied or saw_empty or saw_missing_token)
        )
        name_unavailable = given_name_granted and saw_empty and not saw_denied
        if should_retry:
            return (
                {"profileFetchDenied": True, "profileNameUnavailable": False},
                name_unavailable,
            )
        if name_unavailable:
            return (
                {"profileNameUnavailable": True, "profileFetchDenied": False},
                name_unavailable,
            )
        return ({}, name_unavailable)

    @staticmethod
    def finalize(active: dict, patch: dict, now: int, name_unavailable: bool) -> dict:
        user_name = (
            patch.get("fullName") or patch.get("givenName") or active.get("userName") or None
        )
        user_email = patch.get("userEmail") or active.get("userEmail") or None
        if user_name:
            patch.update(
                {
                    "userName": user_name,
                    "profileFetchDenied": False,
                    "profileNameUnavailable": False,
                }
            )
        if user_name and user_email:
            patch.update({"listenerProfileResolvedAt": now, "listenerProfileSkipUntil": None})
        elif not user_name and not user_email and not name_unavailable:
            patch["listenerProfileSkipUntil"] = now + AlexaProfileModule._PROFILE_BACKOFF_MS
        return patch


class ListenerProfileService:
    __slots__ = ("_settings", "_listeners")

    def __init__(self, settings: AlexaSettingsClient, listeners: Listener) -> None:
        self._settings = settings
        self._listeners = listeners

    async def ensure_listener_profile(self, handler_input, store: dict) -> dict:
        active = store or {}
        now = int(time.time() * 1000)
        resolved_at = active.get("listenerProfileResolvedAt") or 0
        skip_until = active.get("listenerProfileSkipUntil") or 0
        if AlexaProfilePolicy.is_fresh(active, now):
            return {}
        if skip_until and now < skip_until:
            return {}
        requests = AlexaProfilePolicy.requests(active)
        if not requests:
            patch = {}
            if not resolved_at or now - resolved_at >= AlexaProfileModule._PROFILE_TTL_MS:
                patch["listenerProfileResolvedAt"] = now
            return patch
        results = await asyncio.gather(
            *(
                self._settings.get_profile_setting(handler_input, path, label=path)
                for _, path in requests
            )
        )
        statuses = [result["status"] for result in results]
        patch = {}
        for (field, _), result in zip(requests, results):
            if result["value"]:
                patch[field] = result["value"]
        given_name_granted = RequestContext.has_permission(
            handler_input, permission_scopes.PROFILE_GIVEN_NAME_READ
        )
        availability, name_unavailable = AlexaProfilePolicy.availability(
            statuses, given_name_granted
        )
        patch.update(availability)
        return AlexaProfilePolicy.finalize(active, patch, now, name_unavailable)

    async def apply_listener_profile(self, handler_input) -> dict:
        patch = await self.ensure_listener_profile(
            handler_input, self._listeners.snapshot(handler_input)
        )
        if patch:
            self._listeners.apply_profile(handler_input, patch)
        return self._listeners.snapshot(handler_input)
