from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.services.storage.persistence import update_store
from src.utils.skill_request import get_access_token, get_person_id, get_user_id

logger = logging.getLogger(__name__)


class IdentityInterceptor(AbstractRequestInterceptor):
    async def process(self, handler_input) -> None:
        user_id = get_user_id(handler_input)
        attrs = handler_input.attributes_manager.request_attributes
        attrs["_identity"] = {
            "alexaUserId": user_id,
            "personId": get_person_id(handler_input),
            "accountLinked": bool(get_access_token(handler_input)),
        }
        if not user_id:
            logger.warning("Hear request rejected for backend dispatch: missing Alexa user ID")
            return
        update_store(handler_input, {"alexaUserId": user_id})
