from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.models.listener import IdentityContext, PrincipalType
from src.models.user import User


class IdentityPolicy:
    logger = logging.getLogger(__name__)

    @staticmethod
    def _get_envelope_value(envelope, *path):
        node = envelope
        for key in path:
            if node is None:
                return None
            try:
                node = getattr(node, key)
            except (AttributeError, TypeError):
                try:
                    node = node[key]
                except (KeyError, TypeError, IndexError):
                    return None
        return node

    @staticmethod
    def _text(value) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def capture(handler_input) -> IdentityContext:
        envelope = handler_input.request_envelope
        user_id = IdentityPolicy._text(AlexaRequest.get_user_id(handler_input))
        person_id = IdentityPolicy._text(
            IdentityPolicy._get_envelope_value(
                envelope, "context", "System", "person", "personId"
            )
        )
        device_id = IdentityPolicy._text(
            IdentityPolicy._get_envelope_value(
                envelope, "context", "System", "device", "deviceId"
            )
        )
        skill_id = IdentityPolicy._text(
            IdentityPolicy._get_envelope_value(
                envelope, "context", "System", "application", "applicationId"
            )
        )
        locale = IdentityPolicy._text(
            IdentityPolicy._get_envelope_value(envelope, "request", "locale")
        )
        principal_type = (
            PrincipalType.RECOGNIZED_PERSON if person_id else PrincipalType.SKILL_USER
        )
        return IdentityContext(
            principal_type=principal_type,
            alexa_user_id=user_id,
            person_id=person_id,
            device_id=device_id,
            skill_id=skill_id,
            locale=locale,
        )


class IdentityInterceptor(AbstractRequestInterceptor):
    def __init__(self, *, deps: object | None = None) -> None:
        self._identity_service = getattr(deps, "listener_identity", None)
        self._user = getattr(deps, "user", None) or User()

    async def process(self, handler_input) -> None:
        identity = IdentityPolicy.capture(handler_input)
        if self._identity_service is not None:
            try:
                identity = await self._identity_service.resolve(handler_input, identity)
            except Exception as exc:
                IdentityPolicy.logger.warning(
                    "Hear: canonical listener resolution failed error=%s fallback=alexa_alias",
                    type(exc).__name__,
                )
        attrs = RequestContext.request(handler_input)
        attrs["_identity"] = identity
        RequestContext.replace_request(handler_input, attrs)
        self._user.configure_persistence_identity(
            handler_input,
            listener_id=identity.listener_id,
            alexa_user_id=identity.alexa_user_id,
        )
        if not identity.alexa_user_id:
            IdentityPolicy.logger.warning(
                "Hear request rejected for backend dispatch: missing Alexa user ID"
            )
