from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.models import IdentityContext
from src.utils.skill_request import get_user_id

logger = logging.getLogger(__name__)


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


class IdentityInterceptor(AbstractRequestInterceptor):
    async def process(self, handler_input) -> None:
        envelope = handler_input.request_envelope
        user_id = get_user_id(handler_input)
        person_id = _get_envelope_value(envelope, "context", "System", "person", "personId")
        device_id = _get_envelope_value(envelope, "context", "System", "device", "deviceId")
        access_token = _get_envelope_value(envelope, "context", "System", "user", "accessToken")
        is_linked = isinstance(access_token, str) and bool(access_token.strip())
        if is_linked and person_id:
            principal_type = "linked_person"
        elif is_linked:
            principal_type = "linked_household"
        elif person_id:
            principal_type = "anonymous_person"
        else:
            principal_type = "anonymous_installation"
        identity = IdentityContext(
            principal_type=principal_type,
            alexa_user_id=user_id or None,
            person_id=person_id or None,
            device_id=device_id or None,
            access_token=access_token or None,
            is_linked=is_linked,
        )
        attrs = handler_input.attributes_manager.request_attributes
        attrs["_identity"] = identity
        handler_input.attributes_manager.request_attributes = attrs
        if not user_id:
            logger.warning("Hear request rejected for backend dispatch: missing Alexa user ID")
