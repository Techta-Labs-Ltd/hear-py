from __future__ import annotations

import math
from uuid import UUID


class ListenerPayload:
    MAX_ALEXA_USER_ID_LENGTH = 1024
    MAX_TEXT_LENGTH = 200
    REGISTRATION_FIELDS = frozenset(
        {
            "action",
            "alexaUserId",
            "listenerId",
            "listenerName",
            "email",
            "city",
            "longitude",
            "latitude",
        }
    )

    @staticmethod
    def text(value: object, maximum: int) -> str | None:
        text = str(value or "").strip()
        return text if 0 < len(text) <= maximum else None

    @staticmethod
    def listener_id(value: object) -> str | None:
        text = ListenerPayload.text(value, 36)
        if not text:
            return None
        try:
            return str(UUID(text))
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def email(value: object) -> str | None:
        text = ListenerPayload.text(value, ListenerPayload.MAX_TEXT_LENGTH)
        if not text or text.count("@") != 1 or any(character.isspace() for character in text):
            return None
        local, domain = text.rsplit("@", 1)
        return text.casefold() if local and "." in domain else None

    @staticmethod
    def number(value: object, minimum: float, maximum: float) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and minimum <= number <= maximum else None

    @staticmethod
    def registration(profile: dict | None) -> dict | None:
        if not isinstance(profile, dict) or set(profile).difference(ListenerPayload.REGISTRATION_FIELDS):
            return None
        alexa_user_id = ListenerPayload.text(
            profile.get("alexaUserId"), ListenerPayload.MAX_ALEXA_USER_ID_LENGTH
        )
        if profile.get("action") != "alexa" or not alexa_user_id or "listenerId" not in profile:
            return None
        listener_id = profile.get("listenerId")
        if listener_id is not None:
            listener_id = ListenerPayload.listener_id(listener_id)
            if not listener_id:
                return None
        body = {
            "action": "alexa",
            "alexaUserId": alexa_user_id,
            "listenerId": listener_id,
        }
        optional = {
            "listenerName": ListenerPayload.text(
                profile.get("listenerName"), ListenerPayload.MAX_TEXT_LENGTH
            ),
            "email": ListenerPayload.email(profile.get("email")),
            "city": ListenerPayload.text(profile.get("city"), ListenerPayload.MAX_TEXT_LENGTH),
            "longitude": ListenerPayload.number(profile.get("longitude"), -180, 180),
            "latitude": ListenerPayload.number(profile.get("latitude"), -90, 90),
        }
        return {**body, **{key: value for key, value in optional.items() if value is not None}}

    @staticmethod
    def resolution(identity: dict | None) -> dict | None:
        if not isinstance(identity, dict):
            return None
        body = {
            key: value
            for key, value in {
                "listenerId": ListenerPayload.listener_id(identity.get("listenerId")),
                "alexaUserId": ListenerPayload.text(
                    identity.get("alexaUserId"), ListenerPayload.MAX_ALEXA_USER_ID_LENGTH
                ),
                "userEmail": ListenerPayload.email(identity.get("userEmail")),
            }.items()
            if value is not None
        }
        return body or None
